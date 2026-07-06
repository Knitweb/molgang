<?php
// Chemistry — the small school-level knowledge base + a formula parser, so NPC peers
// can vote honestly. Faithful port of src/molgang/chemistry.py.
declare(strict_types=1);

final class Chemistry
{
    // symbol => [name_en, name_nl, atomic number]. Mirrors src/molgang/chemistry.py ELEMENTS 1:1.
    public const ELEMENTS = [
        'H'  => ['Hydrogen', 'Waterstof', 1],
        'C'  => ['Carbon', 'Koolstof', 6],
        'N'  => ['Nitrogen', 'Stikstof', 7],
        'O'  => ['Oxygen', 'Zuurstof', 8],
        'Na' => ['Sodium', 'Natrium', 11],
        'Cl' => ['Chlorine', 'Chloor', 17],
        'S'  => ['Sulfur', 'Zwavel', 16],
        'Ca' => ['Calcium', 'Calcium', 20],
        'Fe' => ['Iron', 'IJzer', 26],
        'He' => ['Helium', 'Helium', 2],
        'Mg' => ['Magnesium', 'Magnesium', 12],
        'Al' => ['Aluminium', 'Aluminium', 13],
        'P'  => ['Phosphorus', 'Fosfor', 15],
        'K'  => ['Potassium', 'Kalium', 19],
        'F'  => ['Fluorine', 'Fluor', 9],
        'Si' => ['Silicon', 'Silicium', 14],
        'Zn' => ['Zinc', 'Zink', 30],
        'Br' => ['Bromine', 'Broom', 35],
        'I'  => ['Iodine', 'Jood', 53],
        // steel-slag metals — the SmartSlag/VANELEX valorisation set (#108)
        'Ti' => ['Titanium', 'Titaan', 22],
        'V'  => ['Vanadium', 'Vanadium', 23],
        'Cr' => ['Chromium', 'Chroom', 24],
        'Mn' => ['Manganese', 'Mangaan', 25],
    ];

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
        'N2'  => ['Nitrogen gas', 'Stikstofgas'],
        'CO'  => ['Carbon monoxide', 'Koolmonoxide'],
        'SO2' => ['Sulfur dioxide', 'Zwaveldioxide'],
        'H2SO4' => ['Sulfuric acid', 'Zwavelzuur'],
        'NaOH' => ['Sodium hydroxide', 'Natriumhydroxide'],
        'CaO' => ['Calcium oxide', 'Calciumoxide'],
        'MgO' => ['Magnesium oxide', 'Magnesiumoxide'],
        'Al2O3' => ['Aluminium oxide', 'Aluminiumoxide'],
        'KCl' => ['Potassium chloride', 'Kaliumchloride'],
        'H3PO4' => ['Phosphoric acid', 'Fosforzuur'],
        'H2O2' => ['Hydrogen peroxide', 'Waterstofperoxide'],
        'HNO3' => ['Nitric acid', 'Salpeterzuur'],
        'H2S' => ['Hydrogen sulfide', 'Waterstofsulfide'],
        'NO2' => ['Nitrogen dioxide', 'Stikstofdioxide'],
        'KOH' => ['Potassium hydroxide', 'Kaliumhydroxide'],
        'SiO2' => ['Silicon dioxide', 'Siliciumdioxide'],
        'ZnO' => ['Zinc oxide', 'Zinkoxide'],
        'NaF' => ['Sodium fluoride', 'Natriumfluoride'],
        'KBr' => ['Potassium bromide', 'Kaliumbromide'],
        'KI' => ['Potassium iodide', 'Kaliumjodide'],
        // steel-slag oxides + the vanadium recovery ladder (#108, Slag Run quest)
        'FeO' => ['Iron(II) oxide', 'IJzer(II)oxide'],
        'Fe2O3' => ['Iron(III) oxide', 'IJzer(III)oxide'],
        'TiO2' => ['Titanium dioxide', 'Titaandioxide'],
        'MnO' => ['Manganese(II) oxide', 'Mangaan(II)oxide'],
        'Cr2O3' => ['Chromium(III) oxide', 'Chroom(III)oxide'],
        'V2O3' => ['Vanadium(III) oxide', 'Vanadium(III)oxide'],
        'V2O5' => ['Vanadium(V) oxide', 'Vanadium(V)oxide'],
    ];

    // Curriculum tiers (easiest -> hardest) for graded quests/ladder. Mirrors chemistry.py 1:1.
    public const TIERS = ['elementary', 'middle', 'high'];
    public const TIER_OF = [
        // elements
        'H' => 'elementary', 'O' => 'elementary', 'C' => 'elementary', 'N' => 'elementary', 'He' => 'elementary',
        'Na' => 'middle', 'Cl' => 'middle', 'Ca' => 'middle', 'Fe' => 'middle', 'Mg' => 'middle',
        'F' => 'middle', 'Zn' => 'middle',
        'S' => 'high', 'Al' => 'high', 'P' => 'high', 'K' => 'high', 'Si' => 'high', 'Br' => 'high', 'I' => 'high',
        // molecules
        'H2O' => 'elementary', 'O2' => 'elementary', 'CO2' => 'elementary', 'H2' => 'elementary',
        'NaCl' => 'middle', 'CH4' => 'middle', 'NH3' => 'middle', 'HCl' => 'middle', 'CaCO3' => 'middle',
        'N2' => 'middle', 'CO' => 'middle', 'SiO2' => 'middle', 'NaF' => 'middle',
        'C6H12O6' => 'high', 'SO2' => 'high', 'H2SO4' => 'high', 'NaOH' => 'high', 'CaO' => 'high',
        'MgO' => 'high', 'Al2O3' => 'high', 'KCl' => 'high', 'H3PO4' => 'high',
        'H2O2' => 'high', 'HNO3' => 'high', 'H2S' => 'high', 'NO2' => 'high', 'KOH' => 'high',
        'ZnO' => 'high', 'KBr' => 'high', 'KI' => 'high',
        // steel-slag set — all high tier
        'Ti' => 'high', 'V' => 'high', 'Cr' => 'high', 'Mn' => 'high',
        'FeO' => 'high', 'Fe2O3' => 'high', 'TiO2' => 'high', 'MnO' => 'high',
        'Cr2O3' => 'high', 'V2O3' => 'high', 'V2O5' => 'high',
    ];

    /** Curriculum tier of a symbol/formula, or null if unknown. Pure lookup. */
    public static function tierOf(string $key): ?string
    {
        return self::TIER_OF[trim($key)] ?? null;
    }

    // Reactions (#109): reactants -> products under optional conditions. Balanced iff every element
    // is conserved across the arrow. Mirrors src/molgang/chemistry.py REACTIONS 1:1.
    public const REACTION_TYPES = ['combustion', 'synthesis', 'neutralisation', 'decomposition', 'redox'];
    public const REACTIONS = [
        'combustion-hydrogen' => ['name' => 'Combustion of hydrogen', 'type' => 'combustion', 'tier' => 'middle', 'equation' => '2 H2 + O2 -> 2 H2O @ spark'],
        'combustion-methane' => ['name' => 'Combustion of methane', 'type' => 'combustion', 'tier' => 'middle', 'equation' => 'CH4 + 2 O2 -> CO2 + 2 H2O @ spark'],
        'combustion-carbon' => ['name' => 'Combustion of carbon', 'type' => 'combustion', 'tier' => 'middle', 'equation' => 'C + O2 -> CO2'],
        'synthesis-ammonia' => ['name' => 'Haber synthesis of ammonia', 'type' => 'synthesis', 'tier' => 'high', 'equation' => 'N2 + 3 H2 -> 2 NH3 @ 450C, 200atm, Fe catalyst'],
        'synthesis-sulfur-dioxide' => ['name' => 'Burning sulfur', 'type' => 'synthesis', 'tier' => 'high', 'equation' => 'S + O2 -> SO2 @ burn'],
        'neutralisation-hcl-naoh' => ['name' => 'Neutralisation of hydrochloric acid', 'type' => 'neutralisation', 'tier' => 'high', 'equation' => 'HCl + NaOH -> NaCl + H2O'],
        'decomposition-limestone' => ['name' => 'Decomposition of limestone', 'type' => 'decomposition', 'tier' => 'high', 'equation' => 'CaCO3 -> CaO + CO2 @ heat'],
        'roast-vanadium' => ['name' => 'Oxidative roast of vanadium oxide', 'type' => 'synthesis', 'tier' => 'high', 'equation' => 'V2O3 + O2 -> V2O5 @ 850C oxidative roast'],
        'thermite-iron' => ['name' => 'Thermite reduction of iron oxide', 'type' => 'redox', 'tier' => 'high', 'equation' => 'Fe2O3 + 2 Al -> 2 Fe + Al2O3 @ ignition'],
    ];

    /** Tally elements on one side ("2 H2 + O2") into [element => count], or null on a bad species. */
    private static function tallySide(string $side): ?array
    {
        $total = [];
        foreach (explode('+', $side) as $chunk) {
            if (!preg_match('~^\s*(\d*)\s*([A-Za-z0-9]+)\s*$~', $chunk, $m)) {
                return null;
            }
            $atoms = self::parseFormula($m[2]);
            if ($atoms === null) {
                return null;
            }
            $n = $m[1] !== '' ? (int) $m[1] : 1;
            foreach ($atoms as $sym => $cnt) {
                $total[$sym] = ($total[$sym] ?? 0) + $n * $cnt;
            }
        }
        return $total;
    }

    /** True iff every element is conserved across the arrow. Parses an equation (optional "@ cond"). */
    public static function reactionIsBalanced(string $equation): bool
    {
        $body = preg_replace('~@.*$~', '', $equation);
        $pos = strpos($body, '->');
        if ($pos === false) {
            return false;
        }
        $left = self::tallySide(substr($body, 0, $pos));
        $right = self::tallySide(substr($body, $pos + 2));
        if ($left === null || $right === null) {
            return false;
        }
        ksort($left);
        ksort($right);
        return $left === $right;
    }

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
