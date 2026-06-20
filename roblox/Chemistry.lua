--!strict
-- MOLGANG Chemistry (scheikunde) — Lua mirror of src/molgang/chemistry.py
-- Keep this table in sync with the Python ground truth so a Roblox player's vote means
-- exactly what it means on the Knitweb. ModuleScript; place under ReplicatedStorage/MOLGANG.

local Chemistry = {}

-- symbol -> {name_en, name_nl, atomic number}
Chemistry.ELEMENTS = {
	H = {"Hydrogen", "Waterstof", 1}, C = {"Carbon", "Koolstof", 6},
	N = {"Nitrogen", "Stikstof", 7}, O = {"Oxygen", "Zuurstof", 8},
	Na = {"Sodium", "Natrium", 11}, Cl = {"Chlorine", "Chloor", 17},
	S = {"Sulfur", "Zwavel", 16}, Ca = {"Calcium", "Calcium", 20},
	Fe = {"Iron", "IJzer", 26}, He = {"Helium", "Helium", 2},
	Mg = {"Magnesium", "Magnesium", 12}, Al = {"Aluminium", "Aluminium", 13},
	P = {"Phosphorus", "Fosfor", 15}, K = {"Potassium", "Kalium", 19},
}

-- formula -> {name_en, name_nl}: the lesson set newcomers learn first
Chemistry.MOLECULES = {
	H2O = {"Water", "Water"}, CO2 = {"Carbon dioxide", "Koolstofdioxide"},
	O2 = {"Oxygen gas", "Zuurstofgas"}, NaCl = {"Table salt", "Keukenzout"},
	CH4 = {"Methane", "Methaan"}, NH3 = {"Ammonia", "Ammoniak"},
	HCl = {"Hydrochloric acid", "Zoutzuur"}, C6H12O6 = {"Glucose", "Glucose"},
	CaCO3 = {"Calcium carbonate", "Calciumcarbonaat"}, H2 = {"Hydrogen gas", "Waterstofgas"},
	N2 = {"Nitrogen gas", "Stikstofgas"}, CO = {"Carbon monoxide", "Koolmonoxide"},
	SO2 = {"Sulfur dioxide", "Zwaveldioxide"}, H2SO4 = {"Sulfuric acid", "Zwavelzuur"},
	NaOH = {"Sodium hydroxide", "Natriumhydroxide"}, CaO = {"Calcium oxide", "Calciumoxide"},
	MgO = {"Magnesium oxide", "Magnesiumoxide"}, Al2O3 = {"Aluminium oxide", "Aluminiumoxide"},
	KCl = {"Potassium chloride", "Kaliumchloride"}, H3PO4 = {"Phosphoric acid", "Fosforzuur"},
}

-- Curriculum tiers (easiest -> hardest) so quests/missions/ladder can grade content. Mirrors
-- src/molgang/chemistry.py TIERS/_TIER_OF 1:1. symbol/formula -> tier.
Chemistry.TIERS = {"elementary", "middle", "high"}
Chemistry.TIER_OF = {
	-- elements
	H = "elementary", O = "elementary", C = "elementary", N = "elementary", He = "elementary",
	Na = "middle", Cl = "middle", Ca = "middle", Fe = "middle", Mg = "middle",
	S = "high", Al = "high", P = "high", K = "high",
	-- molecules
	H2O = "elementary", O2 = "elementary", CO2 = "elementary", H2 = "elementary",
	NaCl = "middle", CH4 = "middle", NH3 = "middle", HCl = "middle", CaCO3 = "middle",
	N2 = "middle", CO = "middle",
	C6H12O6 = "high", SO2 = "high", H2SO4 = "high", NaOH = "high", CaO = "high",
	MgO = "high", Al2O3 = "high", KCl = "high", H3PO4 = "high",
}

-- Curriculum tier of a symbol/formula, or nil if unknown. Pure lookup; isCorrect stays authority.
function Chemistry.tierOf(key: string): string?
	return Chemistry.TIER_OF[key]
end

-- Parse a flat formula (e.g. "C6H12O6") into {element = count}. Errors on unknown element.
function Chemistry.parseFormula(formula: string): { [string]: number }
	local atoms: { [string]: number } = {}
	local i = 1
	while i <= #formula do
		local sym, num = string.match(formula, "^(%u%l?)(%d*)", i)
		if not sym then error("unparseable formula near " .. string.sub(formula, i)) end
		if not Chemistry.ELEMENTS[sym] then error("unknown element " .. sym) end
		atoms[sym] = (atoms[sym] or 0) + (num ~= "" and tonumber(num) or 1)
		i = i + #sym + #num
	end
	return atoms
end

-- Ground truth an honest player uses to vote: is the proposed bond real chemistry?
function Chemistry.isCorrect(formula: string): boolean
	if not Chemistry.MOLECULES[formula] then return false end
	local ok = pcall(Chemistry.parseFormula, formula)
	return ok
end

return Chemistry
