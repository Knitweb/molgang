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
	F = {"Fluorine", "Fluor", 9}, Si = {"Silicon", "Silicium", 14},
	Zn = {"Zinc", "Zink", 30}, Br = {"Bromine", "Broom", 35},
	I = {"Iodine", "Jood", 53},
	-- steel-slag metals — the SmartSlag/VANELEX valorisation set (#108)
	Ti = {"Titanium", "Titaan", 22}, V = {"Vanadium", "Vanadium", 23},
	Cr = {"Chromium", "Chroom", 24}, Mn = {"Manganese", "Mangaan", 25},
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
	H2O2 = {"Hydrogen peroxide", "Waterstofperoxide"}, HNO3 = {"Nitric acid", "Salpeterzuur"},
	H2S = {"Hydrogen sulfide", "Waterstofsulfide"}, NO2 = {"Nitrogen dioxide", "Stikstofdioxide"},
	KOH = {"Potassium hydroxide", "Kaliumhydroxide"}, SiO2 = {"Silicon dioxide", "Siliciumdioxide"},
	ZnO = {"Zinc oxide", "Zinkoxide"}, NaF = {"Sodium fluoride", "Natriumfluoride"},
	KBr = {"Potassium bromide", "Kaliumbromide"}, KI = {"Potassium iodide", "Kaliumjodide"},
	-- steel-slag oxides + the vanadium recovery ladder (#108, Slag Run quest)
	FeO = {"Iron(II) oxide", "IJzer(II)oxide"}, Fe2O3 = {"Iron(III) oxide", "IJzer(III)oxide"},
	TiO2 = {"Titanium dioxide", "Titaandioxide"}, MnO = {"Manganese(II) oxide", "Mangaan(II)oxide"},
	Cr2O3 = {"Chromium(III) oxide", "Chroom(III)oxide"}, V2O3 = {"Vanadium(III) oxide", "Vanadium(III)oxide"},
	V2O5 = {"Vanadium(V) oxide", "Vanadium(V)oxide"},
}

-- Curriculum tiers (easiest -> hardest) so quests/missions/ladder can grade content. Mirrors
-- src/molgang/chemistry.py TIERS/_TIER_OF 1:1. symbol/formula -> tier.
Chemistry.TIERS = {"elementary", "middle", "high"}
Chemistry.TIER_OF = {
	-- elements
	H = "elementary", O = "elementary", C = "elementary", N = "elementary", He = "elementary",
	Na = "middle", Cl = "middle", Ca = "middle", Fe = "middle", Mg = "middle",
	F = "middle", Zn = "middle",
	S = "high", Al = "high", P = "high", K = "high", Si = "high", Br = "high", I = "high",
	-- molecules
	H2O = "elementary", O2 = "elementary", CO2 = "elementary", H2 = "elementary",
	NaCl = "middle", CH4 = "middle", NH3 = "middle", HCl = "middle", CaCO3 = "middle",
	N2 = "middle", CO = "middle", SiO2 = "middle", NaF = "middle",
	C6H12O6 = "high", SO2 = "high", H2SO4 = "high", NaOH = "high", CaO = "high",
	MgO = "high", Al2O3 = "high", KCl = "high", H3PO4 = "high",
	H2O2 = "high", HNO3 = "high", H2S = "high", NO2 = "high", KOH = "high",
	ZnO = "high", KBr = "high", KI = "high",
	-- steel-slag set — all high tier
	Ti = "high", V = "high", Cr = "high", Mn = "high",
	FeO = "high", Fe2O3 = "high", TiO2 = "high", MnO = "high",
	Cr2O3 = "high", V2O3 = "high", V2O5 = "high",
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

-- Reactions (#109): reactants -> products under optional conditions. Balanced iff every element is
-- conserved across the arrow. Mirrors src/molgang/chemistry.py REACTIONS + reaction_is_balanced 1:1.
Chemistry.REACTION_TYPES = {"combustion", "synthesis", "neutralisation", "decomposition", "redox"}
Chemistry.REACTIONS = {
	["combustion-hydrogen"] = {name = "Combustion of hydrogen", type = "combustion", tier = "middle", equation = "2 H2 + O2 -> 2 H2O @ spark"},
	["combustion-methane"] = {name = "Combustion of methane", type = "combustion", tier = "middle", equation = "CH4 + 2 O2 -> CO2 + 2 H2O @ spark"},
	["combustion-carbon"] = {name = "Combustion of carbon", type = "combustion", tier = "middle", equation = "C + O2 -> CO2"},
	["synthesis-ammonia"] = {name = "Haber synthesis of ammonia", type = "synthesis", tier = "high", equation = "N2 + 3 H2 -> 2 NH3 @ 450C, 200atm, Fe catalyst"},
	["synthesis-sulfur-dioxide"] = {name = "Burning sulfur", type = "synthesis", tier = "high", equation = "S + O2 -> SO2 @ burn"},
	["neutralisation-hcl-naoh"] = {name = "Neutralisation of hydrochloric acid", type = "neutralisation", tier = "high", equation = "HCl + NaOH -> NaCl + H2O"},
	["decomposition-limestone"] = {name = "Decomposition of limestone", type = "decomposition", tier = "high", equation = "CaCO3 -> CaO + CO2 @ heat"},
	["roast-vanadium"] = {name = "Oxidative roast of vanadium oxide", type = "synthesis", tier = "high", equation = "V2O3 + O2 -> V2O5 @ 850C oxidative roast"},
	["thermite-iron"] = {name = "Thermite reduction of iron oxide", type = "redox", tier = "high", equation = "Fe2O3 + 2 Al -> 2 Fe + Al2O3 @ ignition"},
}

-- Tally elements on one side ("2 H2 + O2") into {element = count}; errors on a bad species.
local function tallySide(side: string): { [string]: number }
	local total: { [string]: number } = {}
	for chunk in string.gmatch(side, "[^+]+") do
		local coeff, formula = string.match(chunk, "^%s*(%d*)%s*([A-Za-z0-9]+)%s*$")
		if not formula then error("unparseable species " .. chunk) end
		local n = (coeff ~= "" and tonumber(coeff)) or 1
		for sym, cnt in pairs(Chemistry.parseFormula(formula)) do
			total[sym] = (total[sym] or 0) + n * cnt
		end
	end
	return total
end

-- True iff every element is conserved across the arrow. Parses an equation (optional "@ conditions").
function Chemistry.reactionIsBalanced(equation: string): boolean
	local body = string.gsub(equation, "@.*$", "")
	local arrow = string.find(body, "->", 1, true)
	if not arrow then return false end
	local okL, left = pcall(tallySide, string.sub(body, 1, arrow - 1))
	local okR, right = pcall(tallySide, string.sub(body, arrow + 2))
	if not okL or not okR then return false end
	for k, v in pairs(left) do if right[k] ~= v then return false end end
	for k, v in pairs(right) do if left[k] ~= v then return false end end
	return true
end

return Chemistry
