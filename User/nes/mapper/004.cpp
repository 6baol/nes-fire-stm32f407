#include "nes_mapper.h"

/* MMC3 / mapper 4.  The scanline IRQ model is documented with its clock hook. */
static uint8 mmc3_bank_select;
static uint8 mmc3_regs[8];
static uint8 mmc3_irq_counter,mmc3_irq_latch,mmc3_irq_reload;
static uint8 mmc3_irq_enabled,mmc3_irq_pending;
uint8 mmc3_sram_control;

void MAP4_IRQLevel(void)
{
    cpuirq = (mmc3_irq_enabled && mmc3_irq_pending) ? 1 : 0;
}

void MAP4_HSync(int scanline)
{
    (void)scanline;
    if(!mmc3_irq_counter || mmc3_irq_reload) {
        mmc3_irq_counter = mmc3_irq_latch;
        mmc3_irq_reload = 0;
    } else {
        --mmc3_irq_counter;
    }
    if(!mmc3_irq_counter && mmc3_irq_enabled) mmc3_irq_pending = 1;
    MAP4_IRQLevel();
}

static void MAP4_UpdatePrg(void)
{
    uint32 last = num_8k_ROM_banks - 1;
    if(mmc3_bank_select & 0x40) {
        set_CPU_banks(last - 1, mmc3_regs[7], mmc3_regs[6], last);
    } else {
        set_CPU_banks(mmc3_regs[6], mmc3_regs[7], last - 1, last);
    }
}

static void MAP4_UpdateChr(void)
{
    uint8 pair0 = mmc3_regs[0] & 0xFE;
    uint8 pair1 = mmc3_regs[1] & 0xFE;
    if(mmc3_bank_select & 0x80) {
        set_PPU_banks(mmc3_regs[2], mmc3_regs[3], mmc3_regs[4], mmc3_regs[5],
                      pair0, pair0 + 1, pair1, pair1 + 1);
    } else {
        set_PPU_banks(pair0, pair0 + 1, pair1, pair1 + 1,
                      mmc3_regs[2], mmc3_regs[3], mmc3_regs[4], mmc3_regs[5]);
    }
}

void MAP4_Reset(void)
{
    memset(mmc3_regs, 0, sizeof(mmc3_regs));
    mmc3_regs[1] = 2;
    mmc3_regs[2] = 4;
    mmc3_regs[3] = 5;
    mmc3_regs[4] = 6;
    mmc3_regs[5] = 7;
    mmc3_bank_select = 0;
    mmc3_sram_control = 0x80;
    mmc3_irq_counter = mmc3_irq_latch = mmc3_irq_reload = 0;
    mmc3_irq_enabled = mmc3_irq_pending = 0;
    MAP4_IRQLevel();
    MAP4_UpdatePrg();
    MAP4_UpdateChr();
}

void MAP4_MemoryWrite(uint16 addr, uint8 data)
{
    switch(addr & 0xE001) {
        case 0x8000:
            mmc3_bank_select = data;
            MAP4_UpdatePrg();
            MAP4_UpdateChr();
            break;
        case 0x8001:
            mmc3_regs[mmc3_bank_select & 7] = data;
            if((mmc3_bank_select & 7) >= 6) MAP4_UpdatePrg();
            else MAP4_UpdateChr();
            break;
        case 0xA000:
            /* MMC3 bit 0 drives CIRAM A10: 0 = PPU A10 (vertical
             * mirroring), 1 = PPU A11 (horizontal mirroring).
             * This is opposite to the iNES header mirroring bit. */
            if(data & 1) set_mirroring(0, 0, 1, 1);
            else set_mirroring(0, 1, 0, 1);
            break;
        case 0xA001:
            mmc3_sram_control = data & 0xC0;
            break;
        case 0xC000:
            mmc3_irq_latch = data;
            break;
        case 0xC001:
            mmc3_irq_reload = 1;
            break;
        case 0xE000:
            mmc3_irq_enabled = 0;
            mmc3_irq_pending = 0;
            MAP4_IRQLevel();
            break;
        case 0xE001:
            mmc3_irq_enabled = 1;
            MAP4_IRQLevel();
            break;
        default:
            break;
    }
}

void MAP4_Init(void)
{
    NES_Mapper->Reset = MAP4_Reset;
    NES_Mapper->Write = MAP4_MemoryWrite;
    NES_Mapper->HSync = MAP4_HSync;
}
