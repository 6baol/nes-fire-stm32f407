#include "bsp_joystick.h"
#include "bsp_joystick_hw.h"
#include "game_config.h"
#include "stm32f4xx_hal.h"
#include <math.h>
#include <string.h>

static ADC_HandleTypeDef adc;
static JoystickState state;
static uint8_t phase,adc_reinit;
#define JOY_RETRY_MS 2u
#define JOY_STALE_MS 30u
static uint32_t deadline, started, sum_x, sum_y;
static uint16_t samples, min_x, min_y, max_x, max_y;
static uint32_t block_x,block_y;
static float filtered_x, filtered_y;
static uint32_t last_pair;

void Joystick_Calibrate(void)
{
    state.calibrated = 0; state.x = 0; state.y = 0;
    samples = 0; sum_x = sum_y = 0;block_x=block_y=0;
    min_x = min_y = 4095; max_x = max_y = 0;
}

uint8_t Joystick_Init(void)
{
    GPIO_InitTypeDef gpio = {0};
    memset(&state, 0, sizeof(state));
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_ADC1_CLK_ENABLE();
    gpio.Mode = GPIO_MODE_ANALOG; gpio.Pull = GPIO_NOPULL;
    gpio.Pin = JOYSTICK_X_PIN; HAL_GPIO_Init(JOYSTICK_X_PORT, &gpio);
    gpio.Pin = JOYSTICK_Y_PIN; HAL_GPIO_Init(JOYSTICK_Y_PORT, &gpio);
    gpio.Mode = GPIO_MODE_INPUT; gpio.Pull = GPIO_PULLUP;
    gpio.Pin = JOYSTICK_SW_PIN; HAL_GPIO_Init(JOYSTICK_SW_PORT, &gpio);
    adc.Instance = ADC1;
    adc.Init.ClockPrescaler = ADC_CLOCK_SYNC_PCLK_DIV4;
    adc.Init.Resolution = ADC_RESOLUTION_12B;
    adc.Init.ScanConvMode = DISABLE; adc.Init.ContinuousConvMode = DISABLE;
    adc.Init.DiscontinuousConvMode = DISABLE;
    adc.Init.ExternalTrigConvEdge = ADC_EXTERNALTRIGCONVEDGE_NONE;
    adc.Init.ExternalTrigConv = ADC_SOFTWARE_START;
    adc.Init.DataAlign = ADC_DATAALIGN_RIGHT; adc.Init.NbrOfConversion = 1;
    adc.Init.DMAContinuousRequests = DISABLE;
    adc.Init.EOCSelection = ADC_EOC_SINGLE_CONV;
    Joystick_Calibrate();
    deadline = HAL_GetTick(); phase = 0;last_pair=deadline;
    adc_reinit=HAL_ADC_Init(&adc)!=HAL_OK;
    if(adc_reinit) {++state.errors;deadline+=JOY_RETRY_MS;return 1;}
    return 0;
}

static uint8_t begin_conversion(uint32_t channel)
{
    ADC_ChannelConfTypeDef config = {0};
    config.Channel = channel; config.Rank = 1;
    config.SamplingTime = ADC_SAMPLETIME_144CYCLES;
    return HAL_ADC_ConfigChannel(&adc,&config) != HAL_OK || HAL_ADC_Start(&adc) != HAL_OK;
}

static void process_pair(uint32_t now)
{
    float x, y, length, magnitude,alpha;
    uint32_t gap=now-last_pair;
    last_pair=now;++state.pairs;
    if(gap>state.max_pair_gap_ms) state.max_pair_gap_ms=gap;
    /* A 6 ms time constant stays consistent if foreground sampling jitters. */
    if(gap>30) gap=30;
    alpha=(float)gap/(6.0f+(float)gap);
    if(state.calibrated && !state.healthy) {
        /* Restart filtering from the newly recovered input, not stale motion. */
        filtered_x=state.raw_x;filtered_y=state.raw_y;
    }
    state.healthy = 1;
    if (!state.calibrated) {
        if (state.raw_x < 1000 || state.raw_x > 3100 ||
            state.raw_y < 1000 || state.raw_y > 3100) {
            Joystick_Calibrate(); return;
        }
        /* Evaluate stability on 8-pair means. Raw ADC pickup from nearby
         * digital signals must not keep a centred stick uncalibrated forever.
         * The same 1000..3100 centre window and 180-count stability limit stay. */
        sum_x += state.raw_x;sum_y += state.raw_y;
        block_x += state.raw_x;block_y += state.raw_y;++samples;
        if((samples&7u)==0) {
            uint16_t bx=(uint16_t)(block_x/8),by=(uint16_t)(block_y/8);
            block_x=block_y=0;
            if(bx<min_x)min_x=bx;
            if(bx>max_x)max_x=bx;
            if(by<min_y)min_y=by;
            if(by>max_y)max_y=by;
        }
        if (samples < 256) return;
        if (max_x-min_x > 180 || max_y-min_y > 180) { Joystick_Calibrate(); return; }
        state.center_x = (uint16_t)(sum_x / samples);
        state.center_y = (uint16_t)(sum_y / samples);
        filtered_x = state.center_x; filtered_y = state.center_y;
        state.calibrated = 1;
    }
    filtered_x += alpha * (state.raw_x-filtered_x);
    filtered_y += alpha * (state.raw_y-filtered_y);
    x = (filtered_x-state.center_x) / (filtered_x >= state.center_x ?
         4095-state.center_x : state.center_x);
    y = (filtered_y-state.center_y) / (filtered_y >= state.center_y ?
         4095-state.center_y : state.center_y);
    if (GAME_JOY_INVERT_X) x = -x;
    if (GAME_JOY_INVERT_Y) y = -y;
    length = sqrtf(x*x + y*y);
    if (length <= GAME_JOY_DEADZONE) { state.x = state.y = 0; return; }
    magnitude = (length-GAME_JOY_DEADZONE) / (1-GAME_JOY_DEADZONE);
    if (magnitude > 1) magnitude = 1;
    state.x = x / length * magnitude; state.y = y / length * magnitude;
}

void Joystick_Poll(uint32_t now)
{
    /* A sampling outage invalidates freshness, never the confirmed centre.
     * Hold at most 30ms, then stop motion until a complete fresh pair arrives. */
    if((uint32_t)(now-last_pair)>JOY_STALE_MS) {
        state.healthy=0;state.x=state.y=0;
    }
    if (!phase) {
        if ((int32_t)(now-deadline) < 0) return;
        if(adc_reinit || (adc.State&HAL_ADC_STATE_ERROR_INTERNAL)) {
            HAL_ADC_Stop(&adc);
            if(HAL_ADC_Init(&adc)!=HAL_OK) {adc_reinit=1;goto failure;}
            adc_reinit=0;
        }
        deadline = now + 2; started = now;
        if (begin_conversion(JOYSTICK_X_CHANNEL)) goto failure;
        phase = 1; return;
    }
    if(adc.State&HAL_ADC_STATE_ERROR_INTERNAL) {adc_reinit=1;goto failure;}
    if (!__HAL_ADC_GET_FLAG(&adc, ADC_FLAG_EOC)) {
        if ((uint32_t)(now-started) > 5) goto failure;
        return;
    }
    if (phase == 1) {
        state.raw_x = (uint16_t)HAL_ADC_GetValue(&adc);
        HAL_ADC_Stop(&adc);
        if (begin_conversion(JOYSTICK_Y_CHANNEL)) goto failure;
        phase = 2;
    } else {
        state.raw_y = (uint16_t)HAL_ADC_GetValue(&adc);
        HAL_ADC_Stop(&adc); phase = 0; process_pair(now);
    }
    return;
failure:
    HAL_ADC_Stop(&adc);phase=0;deadline=now+JOY_RETRY_MS;++state.errors;
    if(adc.State&HAL_ADC_STATE_ERROR_INTERNAL)adc_reinit=1;
    if((uint32_t)(now-last_pair)>JOY_STALE_MS) {
        state.healthy=0;state.x=state.y=0;
    }
    /* Calibration is only discarded explicitly or during initial learning. */
}

const JoystickState *Joystick_Get(void) { return &state; }
