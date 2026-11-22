#include "game_core.h"
#include <math.h>
#include <string.h>

#define PI_F 3.14159265358979323846f
#define DT (1.0f / GAME_TICK_HZ)

static float clampf(float v, float lo, float hi)
{
    return v < lo ? lo : (v > hi ? hi : v);
}

static void spawn(Game *g, float x, float y, float angle, float speed, uint8_t kind)
{
    unsigned i;
    for (i = 0; i < GAME_ENEMY_BULLETS; ++i) {
        GameBullet *b = &g->bullets[i];
        if (b->active) continue;
        b->x = x; b->y = y;
        b->vx = cosf(angle) * speed; b->vy = sinf(angle) * speed;
        b->radius = kind == 1 ? 5 : 4;
        b->kind = kind; b->active = 1;
        return;
    }
    ++g->dropped_bullets;
}

static void fan(Game *g, float x, float y, unsigned count, float center, float step,
                float speed, uint8_t kind)
{
    unsigned i;
    for (i = 0; i < count; ++i)
        spawn(g, x, y, center + ((float)i - (count - 1) * 0.5f) * step, speed, kind);
}

void GameCore_Init(Game *g)
{
    memset(g, 0, sizeof(*g));
    g->mode = GAME_TITLE;
    g->player_x = GAME_WIDTH * 0.5f;
    g->player_y = GAME_BOTTOM - 60.0f;
}

void GameCore_Start(Game *g)
{
    GameCore_Init(g);
    g->mode = GAME_PLAYING;
    g->lives = 3; g->bombs = 2; g->invincible = 120;
    g->boss_hp = 900;
}

static int swept_hit(float x0, float y0, float x1, float y1,
                     float x, float y, float radius)
{
    float dx = x1 - x0, dy = y1 - y0;
    float length2 = dx * dx + dy * dy;
    float t = length2 > 0.0f ? ((x-x0)*dx + (y-y0)*dy) / length2 : 0.0f;
    t = clampf(t, 0.0f, 1.0f);
    dx = x0 + t * dx - x; dy = y0 + t * dy - y;
    return dx*dx + dy*dy <= radius*radius;
}

static void damage_boss(Game *g, unsigned damage)
{
    if (!g->boss_active) return;
    if (g->boss_hp <= damage) {
        g->boss_hp = 0; g->boss_active = 0;
        g->score += 10000; g->mode = GAME_WON;
    } else g->boss_hp = (uint16_t)(g->boss_hp - damage);
}

static void fire_player(Game *g)
{
    unsigned i, remaining = 2;
    for (i = 0; i < GAME_PLAYER_BULLETS && remaining; ++i) {
        GameBullet *b = &g->shots[i];
        if (b->active) continue;
        b->active = 1; b->x = g->player_x + (remaining == 2 ? -7 : 7);
        b->y = g->player_y - 16; b->vx = 0; b->vy = -620;
        b->radius = 2; b->kind = 0; --remaining;
    }
}

static void stage(Game *g)
{
    unsigned i;
    if (g->tick < 900 && g->tick % 120 == 1) {
        for (i = 0; i < GAME_ENEMIES; ++i) {
            GameEnemy *e = &g->enemies[i];
            if (e->active) continue;
            e->active = 1; e->hp = 12; e->age = 0;
            e->x = 70.0f + (float)((g->tick / 120 * 83) % 340);
            e->y = GAME_TOP + 20; break;
        }
    }
    for (i = 0; i < GAME_ENEMIES; ++i) {
        GameEnemy *e = &g->enemies[i];
        if (!e->active) continue;
        ++e->age; e->y += 55.0f * DT;
        e->x += sinf(e->age * 0.04f) * 0.65f;
        if (e->age % 90 == 0)
            fan(g, e->x, e->y, 5, atan2f(g->player_y-e->y, g->player_x-e->x),
                0.18f, 130.0f, 0);
        if (e->y > GAME_BOTTOM + 20) e->active = 0;
    }
    if (g->tick == 900) g->boss_active = 1;
    if (!g->boss_active) return;
    g->boss_x = GAME_WIDTH * 0.5f + sinf((g->tick-900) * 0.014f) * 125;
    if (g->boss_hp > 600 && g->tick % 55 == 0)
        fan(g, g->boss_x, 160, 18, PI_F * 0.5f + g->tick * 0.007f,
            PI_F*2/18, 110, 0);
    else if (g->boss_hp <= 600 && g->boss_hp > 300 && g->tick % 35 == 0)
        fan(g, g->boss_x, 160, 9, atan2f(g->player_y-160, g->player_x-g->boss_x),
            0.12f, 160, 1);
    else if (g->boss_hp <= 300 && g->tick % 7 == 0)
        fan(g, g->boss_x, 160, 3, g->tick * 0.11f, PI_F*2/3, 145, 2);
}

void GameCore_Update(Game *g, const GameInput *in)
{
    unsigned i, j;
    float x, y, length, speed;
    if (g->mode == GAME_TITLE) {
        if (in->diagnostic) g->mode = GAME_DIAGNOSTIC;
        else if (in->confirm && in->ready) GameCore_Start(g);
        return;
    }
    if (g->mode == GAME_DIAGNOSTIC) {
        if (in->confirm || in->pause) g->mode = GAME_TITLE;
        return;
    }
    if (g->mode == GAME_WON || g->mode == GAME_LOST) {
        if (in->confirm) GameCore_Init(g);
        return;
    }
    if (in->pause) {
        g->mode = g->mode == GAME_PAUSED ? GAME_PLAYING : GAME_PAUSED;
        return;
    }
    if (g->mode != GAME_PLAYING) return;
    /* An ADC failure freezes the simulation instead of leaving a drifting player. */
    if (!in->ready) { g->mode = GAME_PAUSED; return; }
    ++g->tick; g->slow = in->slow;
    if (g->invincible) --g->invincible;
    if (g->bomb_flash) --g->bomb_flash;
    x = in->x; y = in->y; length = sqrtf(x*x + y*y);
    if (length > 1) { x /= length; y /= length; }
    speed = in->slow ? 95.0f : 245.0f;
    g->player_x = clampf(g->player_x + x*speed*DT, 14, GAME_WIDTH-14);
    g->player_y = clampf(g->player_y + y*speed*DT, GAME_TOP+20, GAME_BOTTOM-14);
    if (in->bomb && g->bombs) {
        --g->bombs; memset(g->bullets, 0, sizeof(g->bullets));
        g->invincible = 120; g->bomb_flash = 20;
        damage_boss(g, 120);
        if (g->mode == GAME_WON) return;
    }
    if (g->tick % 6 == 0) fire_player(g);
    stage(g);
    for (i = 0; i < GAME_PLAYER_BULLETS; ++i) {
        GameBullet *b = &g->shots[i];
        float old_y;
        if (!b->active) continue;
        old_y = b->y; b->y += b->vy*DT;
        if (g->boss_active && swept_hit(b->x,old_y,b->x,b->y,g->boss_x,145,29)) {
            b->active = 0; g->score += 5; damage_boss(g, 3);
            if (g->mode == GAME_WON) return;
        }
        for (j = 0; b->active && j < GAME_ENEMIES; ++j) {
            GameEnemy *e = &g->enemies[j];
            if (e->active && swept_hit(b->x,old_y,b->x,b->y,e->x,e->y,16)) {
                b->active = 0;
                if (e->hp <= 3) { e->active = 0; g->score += 100; }
                else e->hp -= 3;
            }
        }
        if (b->y < GAME_TOP-12) b->active = 0;
    }
    for (i = 0; i < GAME_ENEMY_BULLETS; ++i) {
        GameBullet *b = &g->bullets[i];
        float old_x, old_y;
        if (!b->active) continue;
        old_x = b->x; old_y = b->y;
        b->x += b->vx*DT; b->y += b->vy*DT;
        if (!g->invincible && swept_hit(old_x,old_y,b->x,b->y,
                                       g->player_x,g->player_y,b->radius+3)) {
            b->active = 0; --g->lives; g->invincible = 120;
            if (!g->lives) { g->mode = GAME_LOST; return; }
        }
        if (b->x < -12 || b->x > GAME_WIDTH+12 || b->y < GAME_TOP-12 ||
            b->y > GAME_BOTTOM+12) b->active = 0;
    }
    /* Enemy bodies share the same small player hitbox and invulnerability gate. */
    if (!g->invincible) {
        int hit = g->boss_active && swept_hit(g->player_x,g->player_y,
                  g->player_x,g->player_y,g->boss_x,145,30);
        for (i = 0; i < GAME_ENEMIES && !hit; ++i)
            if (g->enemies[i].active)
                hit = swept_hit(g->player_x,g->player_y,g->player_x,g->player_y,
                      g->enemies[i].x,g->enemies[i].y,17);
        if (hit) {
            --g->lives; g->invincible = 120;
            if (!g->lives) g->mode = GAME_LOST;
        }
    }
}

uint16_t GameCore_BulletCount(const Game *g)
{
    unsigned i; uint16_t count = 0;
    for (i = 0; i < GAME_ENEMY_BULLETS; ++i) count += g->bullets[i].active != 0;
    return count;
}
