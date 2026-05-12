#ifndef DATATYPE_H
#define DATATYPE_H

#include <variant>
#include <opencv2/opencv.hpp>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/compression/octree_pointcloud_compression.h>
#include <pcl/octree/octree2buf_base.h>
#include <pcl/octree/impl/octree2buf_base.hpp>

struct Binary_Data{
    uint8_t *buffer;
    size_t size;

    Binary_Data() : buffer(nullptr), size(0){}
    Binary_Data(std::string &_str) : size(_str.size()){
        buffer = new uint8_t[size];
        std::memcpy(buffer, _str.data(), size);
    }

    ~Binary_Data(){
        delete[] buffer;
    }
};

using Datatype = std::variant<
    cv::Mat,
    pcl::PointCloud<pcl::PointXYZ>::Ptr,
    pcl::PointCloud<pcl::PointXYZRGB>::Ptr,
    std::string,
    Binary_Data,
    Binary_Data *
>;

class Data_Wrapper{
    public:
        Data_Wrapper();
        ~Data_Wrapper();
        Data_Wrapper(std::string &_str);
        Data_Wrapper(cv::Mat &_image);
        Data_Wrapper(Binary_Data *_binary_data);
        
        // move constructor
        Data_Wrapper(Data_Wrapper&& other) noexcept
            : data(std::move(other.data)) {}

        // move assignment
        Data_Wrapper& operator=(Data_Wrapper&& other) noexcept {
            if (this != &other) {
                data = std::move(other.data);
            }
            return *this;
        }

    public:
        Datatype data;

    public:
        template<typename T>
        T convert();
};

// Data Wrapper Convert function
template<typename T>
T Data_Wrapper::convert(){
    return std::visit([](auto && arg) -> T{
        using U = std::decay_t<decltype(arg)>;
        if constexpr (std::is_same_v<U, cv::Mat> && std::is_same_v<T, cv::Mat>){
            return arg;
        }else if constexpr(std::is_same_v<U, Binary_Data *> && std::is_same_v<T, Binary_Data *>){
            return arg;
        }else{
            return T{};
        }
    }, data);
}

#endif
