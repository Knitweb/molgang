--!strict
-- MOLGANG Game — Lua mirror of src/molgang/game.py.
-- Same rules as the Python engine: free faucet (pulses + silk), propose a bond, peers vote
-- with a pulse, settle with the BFT k-of-n quorum. Balances here are the local Roblox UX;
-- the authoritative ledger weave happens in the knitweb bridge (see roblox/README.md).
-- ModuleScript under ReplicatedStorage/MOLGANG.

local Chemistry = require(script.Parent.Chemistry)

local Game = {}

Game.FAUCET_PULSES = 50
Game.FAUCET_SILK = 10
Game.VOTE_COST = 1
Game.SILK_PER_BOND = 1

-- BFT supermajority k = floor(2n/3) + 1 — mirrors knitweb.pouw.quorum.default_threshold.
function Game.defaultThreshold(n: number): number
	return math.floor(2 * n / 3) + 1
end

-- A learner. `robloxId` should be the unique Roblox wallet id (Players: player.UserId).
function Game.newPlayer(robloxId: string | number, name: string?)
	return {
		robloxId = tostring(robloxId),
		name = name or ("roblox:" .. tostring(robloxId)),
		pulses = Game.FAUCET_PULSES,
		silk = Game.FAUCET_SILK,
	}
end

function Game.propose(proposer, formula: string, name: string)
	assert(proposer.silk >= Game.SILK_PER_BOND, proposer.name .. " is out of silk")
	proposer.silk -= Game.SILK_PER_BOND
	return { proposer = proposer, bond = { formula = formula, name = name }, votes = {}, settled = false }
end

function Game.honestVerdict(formula: string): string
	return Chemistry.isCorrect(formula) and "confirm" or "mismatch"
end

-- A peer stakes one pulse and records a verdict ("confirm" | "mismatch" | "abstain").
function Game.castVote(round, voter, verdict: string?)
	assert(not round.settled, "round already settled")
	assert(voter.robloxId ~= round.proposer.robloxId, "a proposer cannot vote on their own bond")
	assert(voter.pulses >= Game.VOTE_COST, voter.name .. " has no pulses left to vote")
	verdict = verdict or Game.honestVerdict(round.bond.formula)
	voter.pulses -= Game.VOTE_COST
	local v = { roblox_id = voter.robloxId, verdict = verdict }
	table.insert(round.votes, v)
	return v
end

-- Tally with the same quorum rule as the Python/knitweb side.
function Game.settle(round)
	assert(not round.settled, "round already settled")
	local confirms, mismatches = 0, 0
	for _, v in ipairs(round.votes) do
		if v.verdict == "confirm" then confirms += 1
		elseif v.verdict == "mismatch" then mismatches += 1 end
	end
	local n = #round.votes
	local k = Game.defaultThreshold(n)
	local outcome = "inconclusive"
	if confirms >= k then
		outcome = "confirmed"
		round.proposer.pulses += n          -- earns the staked pot (peers' pulses)
	elseif mismatches >= k then
		outcome = "detected_fault"
	end
	round.settled = true
	round.outcome = outcome
	return outcome
end

return Game
