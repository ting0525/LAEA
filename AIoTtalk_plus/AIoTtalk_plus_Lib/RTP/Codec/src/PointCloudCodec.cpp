#include "PointCloudCodec.h"

PointCloudCodec::PointCloudCodec(){
    // show_statistics can print out the compression result of point cloud
    // 這個版本的 pcl -> PCL 1.10 好像有 bug
    // 使用同一個 OctreePointCloudCompression 壓縮時 ，壓縮結果的壓縮率愈來愈大
    // 所以在每次壓縮 / 解壓縮時宣告新的 OctreePointCloudCompression 物件 
    // 較新的版本 好像可以解決這個問題 -> PCL 1.12
    
    //point_cloud_encoder = new pcl::io::OctreePointCloudCompression<pcl::PointXYZ>(compression_profile, show_statistics);
    //point_cloud_decoder = new pcl::io::OctreePointCloudCompression<pcl::PointXYZ>();
};

PointCloudCodec::PointCloudCodec(bool _is_rgb):is_rgb(_is_rgb){};

PointCloudCodec::~PointCloudCodec(){};

int PointCloudCodec::encode(Datatype &_raw_data, Binary_Data *_encode_data){
    
    std::stringstream compressed_data;

    if(is_rgb){
        if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZRGB>::Ptr>(_raw_data)){
            auto pointcloud = std::get<pcl::PointCloud<pcl::PointXYZRGB>::Ptr>(_raw_data);
            pcl::io::OctreePointCloudCompression<pcl::PointXYZRGB> encoder(compression_profile_xyzrgb, show_statistics);
            encoder.encodePointCloud(pointcloud, compressed_data);
        }else{
            std::cout << "Invalid input data type, the type should be pcl::PointCloud<pcl::PointXYZRGB>::Ptr" << std::endl;
        }
    }else{
        if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_raw_data)){
            auto pointcloud = std::get<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_raw_data);
            pcl::io::OctreePointCloudCompression<pcl::PointXYZ> encoder(compression_profile_xyz, show_statistics);
            encoder.encodePointCloud(pointcloud, compressed_data);
        }else{
            std::cout << "Invalid input data type, the type should be pcl::PointCloud<pcl::PointXYZ>::Ptr" << std::endl;
        }
    }
    
    std::string data_str = compressed_data.str();
    const char *ptr = data_str.c_str();

    _encode_data->size = data_str.size();
    _encode_data->buffer = new uint8_t[_encode_data->size];
    std::copy(ptr, ptr+_encode_data->size, _encode_data->buffer);
    return 0;
}

int PointCloudCodec::decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data){
    std::string data_str((char *)_encode_data->buffer, _encode_data->size);
    std::stringstream compressed_data(data_str);

    if(is_rgb){
        pcl::PointCloud<pcl::PointXYZRGB>::Ptr restore_pointcloud(new pcl::PointCloud<pcl::PointXYZRGB>());
        pcl::io::OctreePointCloudCompression<pcl::PointXYZRGB> decoder;
        decoder.decodePointCloud(compressed_data, restore_pointcloud);
        _decode_data.push_back(std::move(restore_pointcloud));
    }else{
        pcl::PointCloud<pcl::PointXYZ>::Ptr restore_pointcloud(new pcl::PointCloud<pcl::PointXYZ>());
        pcl::io::OctreePointCloudCompression<pcl::PointXYZ> decoder;
        decoder.decodePointCloud(compressed_data, restore_pointcloud);
        _decode_data.push_back(std::move(restore_pointcloud));
    }

    return 0;
}   

// int PointCloudCodec::encode(Datatype &_raw_data, Binary_Data *_encode_data){
//     if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_raw_data)){
//         std::cout << "PointXYZ" << std::endl;
//     }else if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_raw_data)){
//         std::cout << "PointXYZRGB" << std::endl;
//     }
// };

// int PointCloudCodec::decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data){
//     std::string data_str((char *) data->buffer, data->size);
// };

// int PointCloudCodec::encode(const pcl::PointCloud<pcl::PointXYZ>::ConstPtr &pcloud, struct Data *data){
    
//     std::stringstream compressed_data;
//     pcl::io::OctreePointCloudCompression<pcl::PointXYZ> encoder(compression_profile, show_statistics);
//     encoder.encodePointCloud(pcloud, compressed_data);

//     std::string data_str = compressed_data.str();
//     const char *ptr = data_str.c_str();
    
//     data->size = data_str.size();
//     data->buffer = (uint8_t*)malloc(sizeof(uint8_t) * (data->size));
//     memcpy(data->buffer, ptr, data->size);
    
//     return 0;
// };

// int PointCloudCodec::decode(struct Data *data, pcl::PointCloud<pcl::PointXYZ>::Ptr &restore_pcloud){
//     std::string data_str((char *)data->buffer, data->size);
//     std::stringstream compressed_data(data_str);

//     pcl::io::OctreePointCloudCompression<pcl::PointXYZ> decoder;
//     decoder.decodePointCloud(compressed_data, restore_pcloud);

//     return 0;
// };

// int PointCloudCodec::encode(const pcl::PointCloud<pcl::PointXYZRGB>::ConstPtr &pcloud, struct Data *data){

//     std::stringstream compressed_data;

//     pcl::io::OctreePointCloudCompression<pcl::PointXYZRGB> encoder(compression_profile, show_statistics);
//     encoder.encodePointCloud(pcloud, compressed_data);
//     std::string data_str = compressed_data.str();
//     const char *ptr = data_str.c_str();
    
//     data->size = data_str.size();
//     data->buffer = (uint8_t*)malloc(sizeof(uint8_t) * (data->size));
//     memcpy(data->buffer, ptr, data->size);
    
//     return 0;
// };

// int PointCloudCodec::decode(struct Data *data, pcl::PointCloud<pcl::PointXYZRGB>::Ptr &restore_pcloud){
   
//     pcl::io::OctreePointCloudCompression<pcl::PointXYZRGB> decoder;
//     std::string data_str((char *)data->buffer, data->size);
//     std::stringstream compressed_data(data_str);
//     decoder.decodePointCloud(compressed_data, restore_pcloud);
    
//     return 0;
// };