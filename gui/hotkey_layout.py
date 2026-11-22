"""HOTKEYS screen layout (reference 480 × SCREEN_H px)."""

from gui.layout import SCREEN_W, TOP_BAR_H

ROW_X = 5                          # left margin of every row
ROW_W = SCREEN_W - 2 * ROW_X - 18  # keep clear of the scrollbar
ROW_H = 26
ROW_GAP = 2
ROW_MARGIN = 6                     # inner text padding

TOGGLE_Y = TOP_BAR_H + 4
GLOBAL_Y = TOGGLE_Y + ROW_H + 4     # "works in background" switch
SOUND_Y = GLOBAL_Y + ROW_H + 4      # confirmation sound (grouped with the two switches)
HINT_Y = SOUND_Y + ROW_H + 8
VIEW_TOP = 142                      # first scrollable row
VIEW_BOTTOM = 266                   # last scrollable row (exclusive)
RESET_Y = 270
RESET_H = 28

SCROLL_X = SCREEN_W - 11
SCROLL_W = 5

TOGGLE_ZONE_W = 30                 # left part of a row that switches the action on/off
LABEL_INDENT = 34                  # label starts after the row switch
ROW_SWITCH_MAX_H = 15
ROW_SWITCH_X = 6                   # switch left edge inside the row

LABEL_FONT = 11
KEY_FONT = 11
HINT_FONT = 9
STATE_FONT = 10
SWITCH_MAX_H = 17
SWITCH_GAP = 8

NOTE_MS = 1800                     # how long a "swapped" note stays visible
CHORD_CAPTURE_MS = 1500            # wait for the 2nd key of a chord while capturing
