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
}

-- formula -> {name_en, name_nl}: the lesson set newcomers learn first
Chemistry.MOLECULES = {
	H2O = {"Water", "Water"}, CO2 = {"Carbon dioxide", "Koolstofdioxide"},
	O2 = {"Oxygen gas", "Zuurstofgas"}, NaCl = {"Table salt", "Keukenzout"},
	CH4 = {"Methane", "Methaan"}, NH3 = {"Ammonia", "Ammoniak"},
	HCl = {"Hydrochloric acid", "Zoutzuur"}, C6H12O6 = {"Glucose", "Glucose"},
	CaCO3 = {"Calcium carbonate", "Calciumcarbonaat"}, H2 = {"Hydrogen gas", "Waterstofgas"},
}

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
