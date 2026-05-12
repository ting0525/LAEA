#ifndef _PointCloudCodec_H_
#define _PointCloudCodec_H_

#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/compression/octree_pointcloud_compression.h>
#include <pcl/octree/octree2buf_base.h>
#include <pcl/octree/impl/octree2buf_base.hpp>


#include "Common.h"
#include "Codec.h"

// 點雲壓縮
class PointCloudCodec : public Codec{
    public:
        PointCloudCodec();
        PointCloudCodec(bool _is_rgb);
        ~PointCloudCodec();

    private:
        // 可以設定輸出的 profile
        pcl::io::compression_Profiles_e compression_profile_xyz = pcl::io::MED_RES_ONLINE_COMPRESSION_WITHOUT_COLOR;
        pcl::io::compression_Profiles_e compression_profile_xyzrgb = pcl::io::MED_RES_ONLINE_COMPRESSION_WITH_COLOR;
        bool show_statistics = false;
        pcl::io::OctreePointCloudCompression<pcl::PointXYZ> *point_cloud_encoder;
        pcl::io::OctreePointCloudCompression<pcl::PointXYZ> *point_cloud_decoder;
    
    private:
        bool is_rgb = false;

    public:
        int encode(Datatype &_raw_data, Binary_Data *_encode_data);
        int decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data);
        // int encode(Datatype &_raw_data, Binary_Data *_encode_data) override;
        // int decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data) override;
        
        // int encode_XYZ();
        // int encode_XYZRGB();

        // int decode_XYZ();
        // int decode_XYZRGB();

        // int decode()
        // int encode(void *_raw_data, struct Data *encode_data);
        // int decode(struct Data *encode_data, std::vector<pcl::PointCloud<pcl::PointXYZ>::Ptr> &restore_pcloud);

        // XYZ encode
        //int encode(void *_raw_data, struct Data *encode_data);
        //int decode(struct Data *encode_data, std::vector<pcl::PointCloud<pcl::PointXYZ>::Ptr> &restore_pcloud);
        //int encode(const pcl::PointCloud<pcl::PointXYZ>::ConstPtr &pcloud, struct Data *data);
        //int decode(struct Data *data, pcl::PointCloud<pcl::PointXYZ>::Ptr &restore_pcloud);
        
        //XYZRGB encode
        //int encode(const pcl::PointCloud<pcl::PointXYZRGB>::ConstPtr &pcloud, struct Data *data);
        //int decode(struct Data *data, pcl::PointCloud<pcl::PointXYZRGB>::Ptr &restore_pcloud);
};

#endif