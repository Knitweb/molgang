<?php
// Parse — turn a brainstormed knit into a single term or a link between terms.
// Faithful port of src/molgang/knit_parse.py (connectors, LaTeX cleanup).
declare(strict_types=1);

final class Parse
{
    // (regex connector, relation label) — most specific first.
    private const CONNECTORS = [
        ['~\s*(?:->|=>|→|⇒|⟶)\s*~u', 'yields'],
        ['~\s+is\s+an?\s+~iu',        'is-a'],
        ['~\s+(?:is|are|means|equals)\s+~iu', 'is'],
        ['~\s*=\s*~u',                'is'],
        ['~\s*[:≡]\s*~u',             'is'],
    ];

    public static function clean(string $text): string
    {
        $t = trim($text);
        $t = preg_replace('~\\\\[()\[\]]~', '', $t);        // \( \) \[ \]
        $t = str_replace('$', '', $t);
        $t = preg_replace('~[_^]\{([^}]*)\}~', '$1', $t);   // X_{2} -> X2
        $t = preg_replace('~[_^]~', '', $t);
        $t = str_replace('\\', '', $t);
        $t = preg_replace('~[{}]~', '', $t);
        $t = preg_replace('~\s+~u', ' ', $t);
        return trim(trim($t), "()[]·.,; \t\n");
    }

    /** @return array{kind:string,label:string,term?:string,subject?:string,object?:string,relation?:string} */
    public static function knit(string $text): array
    {
        $raw = trim($text);
        foreach (self::CONNECTORS as [$pattern, $rel]) {
            if (preg_match($pattern, $raw, $m, PREG_OFFSET_CAPTURE)) {
                $at = $m[0][1];
                $len = strlen($m[0][0]);
                $subject = self::clean(substr($raw, 0, $at));
                $object  = self::clean(substr($raw, $at + $len));
                if ($subject !== '' && $object !== '' && mb_strtolower($subject) !== mb_strtolower($object)) {
                    return [
                        'kind' => 'link', 'subject' => $subject, 'object' => $object,
                        'relation' => $rel, 'label' => "$subject $rel $object",
                    ];
                }
            }
        }
        $term = self::clean($raw);
        if ($term === '') {
            $term = trim($raw);
        }
        return ['kind' => 'term', 'term' => $term, 'label' => $term];
    }
}
