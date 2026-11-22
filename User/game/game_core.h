#ifndef GAME_CORE_H
#define GAME_CORE_H
#include <stdint.h>
#include "game_config.h"

typedef enum { GAME_TITLE, GAME_DIAGNOSTIC, GAME_PLAYING, GAME_PAUSED,
               GAME_WON, GAME_LOST } GameMode;
typedef struct {
    float x, y;
    uint8_t ready, slow, confirm, bomb, pause, diagnostic;
} GameInput;
typedef struct {
    float x, y, vx, vy;
    uint8_t active, kind, radius;
} GameBullet;
typedef struct {
    float x, y;
    uint16_t hp, age;
    uint8_t active;
} GameEnemy;
typedef struct {
    GameMode mode;
    uint32_t tick, score, dropped_bullets;
    float player_x, player_y, boss_x;
    uint16_t invincible, bomb_flash, boss_hp;
    uint8_t lives, bombs, slow, boss_active;
    GameBullet bullets[GAME_ENEMY_BULLETS];
    GameBullet shots[GAME_PLAYER_BULLETS];
    GameEnemy enemies[GAME_ENEMIES];
} Game;

void GameCore_Init(Game *g);
void GameCore_Start(Game *g);
void GameCore_Update(Game *g, const GameInput *input);
uint16_t GameCore_BulletCount(const Game *g);

#endif
