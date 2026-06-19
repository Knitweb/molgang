<?php
// Progression — XP/levels/titles over woven bonds. Pure, derived game state.
// Faithful port of src/molgang/progression.py.
declare(strict_types=1);

final class Progression
{
    public const XP_PER_WOVEN = 100;
    // XP thresholds → level 1..8
    public const LEVELS = [0, 100, 300, 600, 1000, 1500, 2500, 4000];
    public const TITLES = [
        'Apprentice', 'Student', 'Lab Assistant', 'Chemist', 'Synthesist',
        'Catalyst', 'Alchemist', 'Laureate',
    ];

    public static function levelFor(int $xp): int
    {
        $lvl = 1;
        foreach (self::LEVELS as $i => $threshold) {
            if ($xp >= $threshold) {
                $lvl = $i + 1;
            }
        }
        return $lvl;
    }

    public static function titleFor(int $level): string
    {
        $n = count(self::TITLES);
        return self::TITLES[min($level, $n) - 1];
    }
}
