// SPDX-License-Identifier: MIT
#include "offline_engine.h"
#include <algorithm>
#include <cstdint>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <vector>
// Reads only the fixed upstream fixture format; not the client audio decoder.
static std::vector<float> sample(const std::string &path) {
    std::ifstream input(std::filesystem::u8path(path),std::ios::binary);
    std::vector<unsigned char> data((std::istreambuf_iterator<char>(input)),{});
    auto u16=[&](size_t i){return unsigned(data.at(i))|(unsigned(data.at(i+1))<<8);};
    auto u32=[&](size_t i){return u16(i)|(u16(i+2)<<16);};
    if(data.size()<44 || std::string(data.begin(),data.begin()+4)!="RIFF"
            || std::string(data.begin()+8,data.begin()+12)!="WAVE")throw std::runtime_error("Wrong fixture");
    unsigned rate=0,channels=0,bits=0,format=0;size_t start=0,length=0;
    for(size_t i=12;i+8<=data.size();) {
        auto n=u32(i+4);if(n>data.size()-i-8)throw std::runtime_error("Truncated fixture");
        std::string tag(data.begin()+i,data.begin()+i+4);
        if(tag=="fmt " && n>=16){format=u16(i+8);channels=u16(i+10);rate=u32(i+12);bits=u16(i+22);}
        if(tag=="data"){start=i+8;length=n;break;}i+=8+n+(n&1);
    }
    if(format!=1||channels!=1||rate!=16000||bits!=16||length==0||length%2)throw std::runtime_error("Fixture must be PCM16 mono16k");
    std::vector<float> result(length/2);
    for(size_t i=0;i<result.size();++i)result[i]=static_cast<int16_t>(u16(start+2*i))/32768.0f;
    return result;
}
int main(int argc,char **argv) {
    try {
        if(argc!=3)return 2;
        const auto pcm=sample(argv[2]);
        Capy::Voice::Engine engine(argv[1]);
        auto text=engine.transcribe(pcm,"en",2);
        std::transform(text.begin(),text.end(),text.begin(),[](unsigned char c){return char(std::tolower(c));});
        if(text.find("country")==std::string::npos||text.find("ask")==std::string::npos||engine.progress()!=100)
            throw std::runtime_error("Fixture speech not recognised");
        bool rejected=false;try{engine.transcribe(pcm,"en",2);}catch(const std::invalid_argument &){rejected=true;}
        if(!rejected)throw std::runtime_error("Context reuse accepted");
        Capy::Voice::Engine cancelled(argv[1]);cancelled.cancel();
        rejected=false;try{cancelled.transcribe(pcm,"en",2);}catch(const std::runtime_error &){rejected=true;}
        if(!rejected)throw std::runtime_error("Cancelled job accepted");
        Capy::Voice::Engine invalid(argv[1]);
        rejected=false;try{invalid.transcribe({std::numeric_limits<float>::quiet_NaN()},"en",2);}catch(const std::invalid_argument &){rejected=true;}
        if(!rejected)throw std::runtime_error("NaN sample accepted");
        std::cout<<"CAPY_OFFLINE_ENGINE=PASS recognition,cancellation,single-use,invalid-input\n";
        return 0;
    } catch(const std::exception &e){std::cerr<<"CAPY_OFFLINE_ENGINE=FAIL "<<e.what()<<'\n';return 1;}
}
