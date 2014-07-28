#include "Python.h"
#include "frameobject.h"

/* Prevent bootstraping pdb while a pdb subinterpreter is alive. */
static int alive_pdb_context = 0;

/* A dummy object that ends the tracer subinterpreter when deallocated. */
typedef struct {
    PyObject_HEAD
    PyThreadState *tstate;
} pdbtracerctxobject;

/* Forward declarations. */
static void pdbtracerctx_dealloc(pdbtracerctxobject *);

static PyTypeObject pdbtracerctxtype = {
    PyVarObject_HEAD_INIT(NULL, 0)
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

static int
set_dict_kwds(PyObject *kw, PyObject *address, PyFrameObject *frame)
{
    PyObject *addlist;
    PyObject *host = NULL;
    PyObject *port = NULL;
    int rc = -1;

    assert(PyUnicode_Check(address));
    addlist = PyUnicode_Split(address, NULL, -1);
    if (addlist == NULL)
        return -1;
    if (Py_SIZE(addlist) >= 1) {
        host = PyUnicode_EncodeLocale(PyList_GET_ITEM(addlist, 0), NULL);
        if (host == NULL)
            goto err;
        if (PyDict_SetItemString(kw, "host", host) != 0)
            goto err;
    }
    if (Py_SIZE(addlist) >= 2) {
        port = PyLong_FromUnicodeObject(PyList_GET_ITEM(addlist, 1), 10);
        if (port == NULL)
            goto err;
        if (PyDict_SetItemString(kw, "port", port) != 0)
            goto err;
    }

    if (PyDict_SetItemString(kw, "frame", (PyObject *)frame) != 0)
        goto err;

    rc = 0;
err:
    Py_DECREF(addlist);
    Py_XDECREF(host);
    Py_XDECREF(port);
    return rc;
}

/* Set up pdb in a sub-interpreter to handle the cases where we are stopped in
 * a loop iterating over sys.modules, or within the import system, or while
 * sys.modules or builtins are empty (such as in some test cases), and to
 * avoid circular imports. */
int
bootstrappdb(PyObject *address)
{
    PyThreadState *tstate;
    Py_tracefunc tracefunc;
    PyObject *traceobj;
    PyObject *type, *value, *traceback;
    PyThreadState *mainstate = PyThreadState_GET();
    PyObject *pdb = NULL;
    PyObject *func = NULL;
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

    if ((tstate=Py_NewInterpreter()) == NULL)
        return -1;

    pdb = PyImport_ImportModule("pdb_clone.pdb");
    if (pdb != NULL ) {
        func = PyObject_GetAttrString(pdb, "set_trace_remote");
        if (func == NULL)
            PyErr_SetString(PyExc_AttributeError,
                        "pdb has no attribute 'set_trace_remote'");
        else {
            PyObject *kw = PyDict_New();
            if (kw != NULL) {
                if (set_dict_kwds(kw, address, mainstate->frame) == 0) {
                    PyObject *empty_tuple = PyTuple_New(0);
                    rsock = PyObject_Call(func, empty_tuple, kw);
                    Py_DECREF(empty_tuple);
                }
                Py_DECREF(kw);
            }
        }
    }

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
    Py_XDECREF(pdb);
    Py_XDECREF(func);
    Py_XDECREF(rsock);
    Py_XDECREF(context);
    return rc;
}

int
_bootstrappdb(char *arg)
{
    int rc;
    PyObject *address = PyUnicode_DecodeLocale(arg, NULL);
    if (address == NULL)
        return -1;
    rc = bootstrappdb(address);
    Py_DECREF(address);
    return rc;
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

static struct PyModuleDef bootstrappdb_def = {
    PyModuleDef_HEAD_INIT,
    "bootstrappdb",
    bootstrappdb_doc,
    -1,
    NULL,
};

PyMODINIT_FUNC
PyInit_bootstrappdb(void)
{
    pdbtracerctxtype.tp_new = PyType_GenericNew;
    if (PyType_Ready(&pdbtracerctxtype) < 0)
        return NULL;

    return PyModule_Create(&bootstrappdb_def);
}

