/* Observe the real core's processed input, not a frontend mock. */
#include "NDSSystem.h"
#include "mic.h"
extern "C" int paperos_nds_test_touch(int x,int y,int pressed){
    const UserInput &i=NDS_getFinalUserInput();
    return i.touch.isTouch==(pressed!=0)&&(!pressed||((i.touch.touchX>>4)==x&&(i.touch.touchY>>4)==y));
}
extern "C" int paperos_nds_test_microphone(void){return NDS_getFinalUserInput().mic.micButtonPressed!=0;}
extern "C" int paperos_nds_test_noise_range(void){
    int low=255,high=0;
    for(int n=0;n<512;n++){int sample=Mic_ReadSample();if(sample<low)low=sample;if(sample>high)high=sample;}
    return high-low;
}
