#include "Python.h"
#include "frameobject.h"

/* Prevent bootstraping pdb while a pdb subinterpreter is alive. */
static int alive_pdb_context = 0;

static PyThreadState *bootstrappdb_tstate = NULL;

/* A dummy object that ends the tracer subinterpreter when deallocated. */
typedef struct {
    PyObject_HEAD
    PyThreadState *tstate;
} pdbtracerctxobject;

/* Forward declarations. */
static void pdbtracerctx_dealloc(pdbtracerctxobject *);
static PyThreadState * call_set_trace_remote(PyThreadState *, PyObject **);

static PyTypeObject pdbtracerctxtype = {
    PyObject_HEAD_INIT(NULL)
    0,                                  /*ob_size         */
    "bootstrappdb.context",             /* tp_name        */
    sizeof(pdbtracerctxobject),         /* tp_basicsize   */
    0,                                  /* tp_itemsize    */
    (destructor)pdbtracerctx_dealloc,   /* tp_dealloc     */
    0,                                  /* tp_print       */
    0,                                  /* tp_getattr     */
    0,                                  /* tp_setattr     */
    0,                                  /* tp_reserved    */
    0,                                  /* tp_repr        */
    0,                                  /* tp_as_number   */
    0,                                  /* tp_as_sequence */
    0,                                  /* tp_as_mapping  */
    0,                                  /* tp_hash        */
    0,                                  /* tp_call        */
    0,                                  /* tp_str         */
    0,                                  /* tp_getattro    */
    0,                                  /* tp_setattro    */
    0,                                  /* tp_as_buffer   */
    Py_TPFLAGS_DEFAULT,                 /* tp_flags       */
    "Pdb tracer context",               /* tp_doc         */
};

static struct _frame *
threadstate_getframe(PyThreadState *ignored)
{
    return bootstrappdb_tstate->frame;
}

/* Set up pdb in a sub-interpreter to handle the cases where we are stopped in
 * a loop iterating over sys.modules, or within the import system, or while
 * sys.modules or builtins are empty (such as in some test cases), and to
 * avoid circular imports. */
int
bootstrappdb(void *unused)
{
    PyThreadState *tstate;
    Py_tracefunc tracefunc;
    PyObject *traceobj;
    PyObject *type, *value, *traceback;
    PyThreadState *mainstate = PyThreadState_GET();
    PyObject *rsock = NULL;
    pdbtracerctxobject *context = NULL;
    int rc = -1;

    if (!Py_IsInitialized())
        return 0;

    /* See python issue 21033. */
    if (mainstate->tracing || alive_pdb_context)
        return 0;

    pdbtracerctxtype.tp_new = PyType_GenericNew;
    if (PyType_Ready(&pdbtracerctxtype) < 0)
        return -1;

    if ((tstate=call_set_trace_remote(mainstate, &rsock)) == NULL)
        return -1;

    tracefunc = tstate->c_tracefunc;
    traceobj = tstate->c_traceobj;
    Py_XINCREF(traceobj);
    if (rsock == NULL)
        goto err;
    if (tracefunc == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "Internal error - trace function not set");
        goto err;
    }

    /* The sub-interpreter remains alive until the pdb socket is closed. */
    context = (pdbtracerctxobject *) pdbtracerctxtype.tp_alloc(
                                                    &pdbtracerctxtype, 0);
    if (context == NULL)
        goto err;
    if (PyObject_SetAttrString(rsock, "_subinterp", (PyObject *)context) != 0)
        goto err;
    context->tstate = tstate;
    alive_pdb_context = 1;

    /* Swap the trace function between both tread states. */
    PyEval_SetTrace(NULL, NULL);
    PyThreadState_Swap(mainstate);
    PyEval_SetTrace(tracefunc, traceobj);
    Py_DECREF(traceobj);
    rc = 0;
    goto fin;

err:
    Py_XDECREF(traceobj);
    PyErr_Fetch(&type, &value, &traceback);
    Py_EndInterpreter(tstate);
    PyThreadState_Swap(mainstate);
    if (type)
        PyErr_Restore(type, value, traceback);
fin:
    Py_XDECREF(rsock);
    Py_XDECREF(context);
    return rc;
}

static PyThreadState *
call_set_trace_remote(PyThreadState *mainstate, PyObject **prsock)
{
    PyObject *saved_globals;
    PyObject *saved_locals;
    PyThreadFrameGetter saved_tstate_getframe;
    PyObject *builtins_str = NULL;
    PyObject *builtins = NULL;
    PyObject *globals = NULL;
    PyObject *locals = NULL;
    PyObject *pdb = NULL;
    PyObject *func = NULL;
    PyThreadState *tstate = NULL;

    builtins_str = PyString_InternFromString("__builtins__");
    if (builtins_str == NULL)
        return NULL;
    builtins = PyObject_GetItem(mainstate->frame->f_globals, builtins_str);
    if (builtins == NULL)
        goto fin;
    globals = Py_BuildValue("{OO}", builtins_str, builtins);
    if (globals == NULL)
        goto fin;
    locals = PyDict_New();
    if (locals == NULL)
        goto fin;

    /* Disable the Python 2 restricted mode in the subinterpreter (see
     * PyEval_GetRestricted()) that prevents linecache to open the source
     * files and prevents attribute access. */
    saved_globals = mainstate->frame->f_globals;
    saved_locals = mainstate->frame->f_locals;
    saved_tstate_getframe = _PyThreadState_GetFrame;
    mainstate->frame->f_globals = globals;
    mainstate->frame->f_locals = locals;
    _PyThreadState_GetFrame = threadstate_getframe;
    bootstrappdb_tstate = mainstate;

    if ((tstate=Py_NewInterpreter()) == NULL)
        goto swap;

    pdb = PyImport_ImportModule("pdb_clone.pdb");
    if (pdb != NULL ) {
        func = PyObject_GetAttrString(pdb, "set_trace_remote");
        if (func == NULL)
            PyErr_SetString(PyExc_AttributeError,
                        "pdb has no attribute 'set_trace_remote'");
        else {
            PyObject *kw = PyDict_New();
            if (kw != NULL) {
                if (PyDict_SetItemString(kw, "frame",
                                        (PyObject *)mainstate->frame) == 0) {
                    PyObject *empty_tuple = PyTuple_New(0);
                    *prsock = PyObject_Call(func, empty_tuple, kw);
                    Py_DECREF(empty_tuple);
                }
                Py_DECREF(kw);
            }
        }
    }

swap:
    mainstate->frame->f_globals = saved_globals;
    mainstate->frame->f_locals = saved_locals;
    _PyThreadState_GetFrame = saved_tstate_getframe;
    bootstrappdb_tstate = NULL;
fin:
    Py_XDECREF(builtins_str);
    Py_XDECREF(builtins);
    Py_XDECREF(globals);
    Py_XDECREF(locals);
    Py_XDECREF(pdb);
    Py_XDECREF(func);
    return tstate;
}

static void
pdbtracerctx_dealloc(pdbtracerctxobject *self)
{
    if (self->tstate != NULL) {
        PyThreadState *tstate = PyThreadState_GET();
        PyThreadState_Swap(self->tstate);
        Py_EndInterpreter(self->tstate);
        PyThreadState_Swap(tstate);
        self->tstate = NULL;
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
    alive_pdb_context = 0;
}

PyDoc_STRVAR(bootstrappdb_doc, "A module to bootstrap pdb from gdb.");

#ifndef PyMODINIT_FUNC  /* declarations for DLL import/export */
#define PyMODINIT_FUNC void
#endif
/* Initialization function for the module. */
PyMODINIT_FUNC
initbootstrappdb(void)
{
    pdbtracerctxtype.tp_new = PyType_GenericNew;
    if (PyType_Ready(&pdbtracerctxtype) < 0)
        return;

    Py_InitModule3("bootstrappdb", NULL, bootstrappdb_doc);
}

