// SPDX-License-Identifier: MIT
#include "offline_engine.h"
#include <jni.h>
#include <algorithm>
#include <cstdint>
#include <exception>
namespace {
using Engine = Capy::Voice::Engine;
void fail(JNIEnv *env) {
    if (env->ExceptionCheck()) return;
    auto type = env->FindClass("java/lang/IllegalStateException");
    if (type) env->ThrowNew(type, "Local speech operation failed.");
}
Engine *engine(jlong handle) { return reinterpret_cast<Engine *>(static_cast<intptr_t>(handle)); }
}
extern "C" JNIEXPORT jlong JNICALL Java_org_capybaragram_voice_OfflineSpeech_nativeOpen(JNIEnv *env,jclass,jstring path) {
    if (!path) { fail(env); return 0; }
    const char *text=env->GetStringUTFChars(path,nullptr);
    if (!text) return 0;
    Engine *result=nullptr;
    try { result=new Engine(text); } catch(const std::exception &) { fail(env); }
    env->ReleaseStringUTFChars(path,text);
    return static_cast<jlong>(reinterpret_cast<intptr_t>(result));
}
extern "C" JNIEXPORT void JNICALL Java_org_capybaragram_voice_OfflineSpeech_nativeCancel(JNIEnv *,jclass,jlong handle) {
    if (engine(handle)) engine(handle)->cancel();
}
extern "C" JNIEXPORT jint JNICALL Java_org_capybaragram_voice_OfflineSpeech_nativeProgress(JNIEnv *,jclass,jlong handle) {
    return engine(handle) ? engine(handle)->progress() : 0;
}
extern "C" JNIEXPORT void JNICALL Java_org_capybaragram_voice_OfflineSpeech_nativeClose(JNIEnv *,jclass,jlong handle) {
    delete engine(handle);
}
extern "C" JNIEXPORT jbyteArray JNICALL Java_org_capybaragram_voice_OfflineSpeech_nativeRun(JNIEnv *env,jclass,jlong handle,jfloatArray input,jstring language,jint threads) {
    if (!engine(handle) || !input || !language || env->GetArrayLength(input)<=0
            || env->GetArrayLength(input)>static_cast<jsize>(Engine::MaxSamples)) { fail(env); return nullptr; }
    const char *lang=env->GetStringUTFChars(language,nullptr);
    if (!lang) return nullptr;
    std::vector<float> pcm;
    jbyteArray output=nullptr;
    try {
        pcm.resize(static_cast<size_t>(env->GetArrayLength(input)));
        env->GetFloatArrayRegion(input,0,static_cast<jsize>(pcm.size()),pcm.data());
        if (!env->ExceptionCheck()) {
            auto text=engine(handle)->transcribe(pcm,lang,threads);
            output=env->NewByteArray(static_cast<jsize>(text.size()));
            if (output) env->SetByteArrayRegion(output,0,static_cast<jsize>(text.size()),reinterpret_cast<const jbyte *>(text.data()));
            std::fill(text.begin(),text.end(),'\0');
        }
    } catch (const std::exception &) { fail(env); }
    std::fill(pcm.begin(),pcm.end(),0.0f);
    env->ReleaseStringUTFChars(language,lang);
    return output;
}
