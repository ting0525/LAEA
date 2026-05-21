#include <pybind11/pybind11.h>
#include <pybind11/functional.h>
#include <pybind11/stl_bind.h>
#include <pybind11/embed.h>
#include <pybind11/pytypes.h>
#include <pybind11/numpy.h>
#include <array>
#include <pybind11/stl.h>
#include <pybind11/complex.h>
#include <pybind11/functional.h> 
#include <pybind11/chrono.h>

#include "cvnp/cvnp.h"


#include "Common.h"
#include "RTPSession.h"
#include "DataWrapper.h"
#include "Codec.h"

namespace py = pybind11;

PYBIND11_MODULE(MyTool_pybind11, m){
    m.doc() = "pybind11_modules";
    
    py::class_<CodecParam>(m, "CodecParam")
    .def(py::init<>())
    .def(py::init<int, std::string, std::map<std::string, std::string> &>(),
        py::arg("payload_type_id"),
        py::arg("codec"),
        py::arg("format_params"))
    .def_readwrite("payload_type_id", &CodecParam::payload_type_id)
    .def_readwrite("codec", &CodecParam::codec)
    .def_readwrite("format_params", &CodecParam::format_params);

    py::class_<Data_Wrapper>(m, "Data_Wrapper")
    .def(py::init<>())
    .def(py::init<cv::Mat &>())
    .def(py::init<std::string&>())
    .def("convert_cv_mat", &Data_Wrapper::convert<cv::Mat>, py::return_value_policy::take_ownership)
    .def("convert_raw_bytes", [](Data_Wrapper &self){
        Binary_Data * ptr = self.convert<Binary_Data *>();
        return py::bytes(
            reinterpret_cast<const char*> ((ptr->buffer)), ptr->size
        );
    }, py::return_value_policy::take_ownership);


    py::class_<RTPSession>(m, "RTPSession")
    .def(py::init<>())
    .def("create_session", &RTPSession::create_session)
    .def("destroy_session", &RTPSession::destroy_session)
    .def("create_stream", &RTPSession::create_stream)
    .def("destroy_stream", &RTPSession::destroy_stream)
    .def("send_data", &RTPSession::send_data2)
    .def(
        "get_data",
        &RTPSession::get_data2,
        py::return_value_policy::take_ownership,
        py::call_guard<py::gil_scoped_release>()
    );
}
