// Render settings for the Paladex launch ad. See https://www.remotion.dev/docs/config
import { Config } from "@remotion/cli/config";

// GPU WebGL on Windows (three.js scenes). Use "swangle" on machines without a GPU.
Config.setChromiumOpenGlRenderer("angle");
Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(95);
Config.setCodec("h264");
Config.setCrf(16);
Config.setPixelFormat("yuv420p");
Config.setX264Preset("slow");
Config.setAudioBitrate("320k");
Config.setDelayRenderTimeoutInMilliseconds(120000);
