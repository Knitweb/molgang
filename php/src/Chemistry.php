<?php
// Chemistry — the small school-level knowledge base + a formula parser, so NPC peers
// can vote honestly. Faithful port of src/molgang/chemistry.py.
declare(strict_types=1);

final class Chemistry
{
    // Known molecules: formula => [name_en, name_nl]. The lesson set newcomers learn first.
    public const MOLECULES = [
        'H2O' => ['Water', 'Water'],
        'CO2' => ['Carbon dioxide', 'Koolstofdioxide'],
        'O2'  => ['Oxygen gas', 'Zuurstofgas'],
        'NaCl' => ['Table salt', 'Keukenzout'],
        'CH4' => ['Methane', 'Methaan'],
        'NH3' => ['Ammonia', 'Ammoniak'],
        'HCl' => ['Hydrochloric acid', 'Zoutzuur'],
        'C6H12O6' => ['Glucose', 'Glucose'],
        'CaCO3' => ['Calcium carbonate', 'Calciumcarbonaat'],
        'H2'  => ['Hydrogen gas', 'Waterstofgas'],
    ];

    /** Parse a flat formula (e.g. C6H12O6) into {element: count}, or null if unparseable. */
    public static function parseFormula(string $formula): ?array
    {
        $formula = trim($formula);
        if ($formula === '') {
            return null;
        }
        $atoms = [];
        $pos = 0;
        if (!preg_match_all('~([A-Z][a-z]?)(\d*)~', $formula, $ms, PREG_SET_ORDER | PREG_OFFSET_CAPTURE)) {
            return null;
        }
        foreach ($ms as $m) {
            if ($m[0][1] !== $pos) {
                return null; // gap / unparseable
            }
            $sym = $m[1][0];
            $num = $m[2][0];
            $atoms[$sym] = ($atoms[$sym] ?? 0) + ($num !== '' ? (int) $num : 1);
            $pos = $m[0][1] + strlen($m[0][0]);
        }
        return $pos === strlen($formula) ? $atoms : null;
    }

    /** A term is recognized if it's a known molecule, a valid formula, or a plausible word/phrase. */
    public static function termRecognized(string $term): bool
    {
        $t = trim($term);
        if ($t === '') {
            return false;
        }
        if (isset(self::MOLECULES[$t])) {
            return true;
        }
        if (self::parseFormula($t) !== null) {
            return true;
        }
        return (bool) preg_match("~^[A-Za-z][\\w'’ +/-]{1,}$~u", $t);
    }

    /** Ground truth a bot uses to vote on a parsed knit (term or link). */
    public static function soundClaim(array $parsed): bool
    {
        if (($parsed['kind'] ?? '') === 'link') {
            $s = $parsed['subject'] ?? '';
            $o = $parsed['object'] ?? '';
            return self::termRecognized($s) && self::termRecognized($o)
                && mb_strtolower($s) !== mb_strtolower($o);
        }
        return self::termRecognized($parsed['term'] ?? $parsed['label'] ?? '');
    }

    public static function isChemistry(string $term): bool
    {
        $t = trim($term);
        return isset(self::MOLECULES[$t]) || self::parseFormula($t) !== null;
    }

    public static function suggestedTerms(): array
    {
        return array_keys(self::MOLECULES);
    }
}
