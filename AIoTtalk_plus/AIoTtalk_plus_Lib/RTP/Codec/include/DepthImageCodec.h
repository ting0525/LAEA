#ifndef _DepthImageCodec_H_
#define _DepthImageCodec_H_

#include <opencv2/opencv.hpp>
#include "zdepth.hpp"
#include "Common.h"
#include "Codec.h"

// 深度圖壓縮

class DepthImageCodec : public Codec{
    public:
        DepthImageCodec();
        DepthImageCodec(int _width, int _height);
        ~DepthImageCodec();
    
    public:
        int width;
        int height;

    public:
        zdepth::DepthCompressor compressor;
        zdepth::DepthCompressor decompressor;
    
    public:
        int encode(Datatype &image, Binary_Data *_encode_data) override;
        int decode(Binary_Data *_encode_data, std::vector<Datatype> &_decode_data) override;
        // int encode(void *_raw_data, struct Binary_Data *_encode_data);
        // int decode(struct Binary_Data *_encode_data, std::vector<std::unique_ptr<cv::Mat>> &restore_depth_images);
        //int encode(cv::Mat &depth_image, struct Data *data);
        //int decode(struct Data *data, cv::Mat &restore_depth_image);
};

#endif