#include "DataWrapper.h"

Data_Wrapper::Data_Wrapper(){};
Data_Wrapper::Data_Wrapper(cv::Mat &_image) : data(_image){};
Data_Wrapper::Data_Wrapper(std::string &_str){
    Binary_Data *binary_data = new Binary_Data(_str);
    data = binary_data;
};
Data_Wrapper::Data_Wrapper(Binary_Data *_binary_data) : data(_binary_data){};
Data_Wrapper::~Data_Wrapper(){};