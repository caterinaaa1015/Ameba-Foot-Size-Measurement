/* AMB82-MINI: Wi-Fi H264 RTSP preview for PC-side foot measurement.
 * Configure wifi_secrets.h locally, then select actual camera sensor in IDE.
 * No foot inference and no receipt LEDs: both LEDs remain OFF.
 */
#include "WiFi.h"
#include "StreamIO.h"
#include "VideoStream.h"
#include "RTSP.h"
#include "wifi_secrets.h"

const int FOOT_CHANNEL = 0;
VideoSetting footVideo(1280, 720, 15, VIDEO_H264, 0);
RTSP footRtsp;
StreamIO footStreamer(1, 1);

void printAddress() {
    Serial.print("RTSP_URL=rtsp://");
    Serial.print(WiFi.localIP());
    Serial.print(":");
    Serial.println(footRtsp.getPort());
}

void setup() {
    Serial.begin(115200);
    pinMode(LED_B, OUTPUT); pinMode(LED_G, OUTPUT);
    digitalWrite(LED_B, LOW); digitalWrite(LED_G, LOW);
    while (WiFi.status() != WL_CONNECTED) {
        Serial.println("WIFI_CONNECTING (credentials are not printed)");
        WiFi.begin(FOOT_WIFI_SSID, FOOT_WIFI_PASS);
        delay(3000);
    }
    footVideo.setBitrate(2 * 1024 * 1024);
    Camera.configVideoChannel(FOOT_CHANNEL, footVideo);
    Camera.videoInit();
    footRtsp.configVideo(footVideo);
    footRtsp.begin();
    footStreamer.registerInput(Camera.getStream(FOOT_CHANNEL));
    footStreamer.registerOutput(footRtsp);
    if (footStreamer.begin() != 0) {
        Serial.println("ERROR,STREAM_START");
        while (true) delay(1000);
    }
    Camera.channelBegin(FOOT_CHANNEL);
    Serial.println("READY,AMEBA_FOOT_WIFI");
    printAddress();
}

void loop() {
    static uint32_t lastReport = 0;
    if (millis() - lastReport > 5000) {
        lastReport = millis();
        if (WiFi.status() == WL_CONNECTED) printAddress();
        else Serial.println("WIFI_DISCONNECTED: restore Wi-Fi and press RESET");
    }
    delay(50);
}
