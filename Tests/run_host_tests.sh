#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p Tests/output
cc -std=c11 -Wall -Wextra -Werror -g -O1 -fsanitize=address,undefined \
  -I Tests/mocks -I User/game -I User/render -I User/joystick -I User/lcd \
  Tests/test_game.c User/game/game_core.c User/render/renderer.c User/lcd/fonts.c \
  -lm -o Tests/output/test_game
Tests/output/test_game Tests/output > Tests/output/results.txt
cc -std=c11 -Wall -Wextra -Werror -g -O1 -fsanitize=address,undefined \
  -I Tests/mocks -I User/game -I User/joystick \
  Tests/test_joystick.c User/joystick/bsp_joystick.c -lm -o Tests/output/test_joystick
Tests/output/test_joystick >> Tests/output/results.txt
cc -std=c11 -Wall -Wextra -Werror -g -O1 -fsanitize=address,undefined \
  -I Tests/mocks -I User/nes -I User/lcd \
  Tests/test_menu.c User/nes/nes_menu.c User/nes/nes_posters.c -o Tests/output/test_menu
Tests/output/test_menu >> Tests/output/results.txt
cat Tests/output/results.txt
