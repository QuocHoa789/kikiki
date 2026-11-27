--!nonstrict
--[[
	apiroblox.luau — Roblox API stub for Luraph deobfuscation
	==========================================================
	Provides a complete-enough Roblox environment so obfuscated scripts
	(Luraph VM output) can run OUTSIDE Roblox — in the Luau CLI or the
	luraph-v14.8-toolkit sandbox — without "attempt to index nil" errors.

	returns an environment table ready for setfenv(protected_chunk, env).

	Includes:
	  * game (with GetService for every common service)
	  * Instance.new with property/event stubs
	  * workspace, script, Players, StarterGui, ReplicatedStorage...
	  * Enum with common enums + EnumItem/EnumType strings
	  * task (wait/spawn/defer/delay/cancel)
	  * datatypes: Vector3, Vector2, CFrame, UDim, UDim2, Color3,
	    BrickColor, NumberRange, NumberSequence, ColorSequence,
	    TweenInfo, Region3, Ray, Random
	  * events with Connect/Disconnect/Wait/Fire
	  * shared, _G, getgenv, hookfunction-style hooks (no-ops)
	  * HttpService stub (JSONEncode/JSONDecode/GetAsync/PostAsync)
]]

local env = {}

-- ---------------------------------------------------------------------------
-- helpers
-- ---------------------------------------------------------------------------

local function make_signal()
	local handlers = {}
	local signal = {}
	function signal:Connect(fn)
		table.insert(handlers, fn)
		return {
			Disconnect = function()
				for i, h in ipairs(handlers) do
					if h == fn then table.remove(handlers, i) break end
				end
			end,
			Connected = true,
		}
	end
	function signal:Wait()
		return nil
	end
	function signal:Fire(...)
		for _, fn in ipairs(handlers) do
			local ok = pcall(fn, ...)
		end
	end
	signal.Once = function(self, fn) return self:Connect(fn) end
	return signal
end

local function make_instance(class)
	local inst
	local props = { ClassName = class, Name = class, Parent = nil }
	local children = {}
	inst = {
		ClassName = class,
		Destroyed = false,
		Destroying = make_signal(),
		AncestryChanged = make_signal(),
		ChildAdded = make_signal(),
		ChildRemoved = make_signal(),
		Changed = make_signal(),
		GetPropertyChangedSignal = function(_, prop)
			return make_signal()
		end,
		FindFirstChild = function(_, name, recursive)
			for _, c in ipairs(children) do
				if c.Name == name then return c end
			end
			return nil
		end,
		FindFirstChildOfClass = function(_, cls)
			for _, c in ipairs(children) do
				if c.ClassName == cls then return c end
			end
			return nil
		end,
		WaitForChild = function(_, name, timeout)
			for _, c in ipairs(children) do
				if c.Name == name then return c end
			end
			return nil
		end,
		GetChildren = function() return children end,
		GetDescendants = function() return children end,
		IsA = function(_, cls) return class == cls end,
		GetFullName = function() return class end,
		ClearAllChildren = function() children = {} end,
		Destroy = function() inst.Destroyed = true end,
		Clone = function() return make_instance(class) end,
		AddChild = function(_, c) table.insert(children, c) end,
	}
	setmetatable(inst, {
		__index = function(_, k)
			-- unknown property: return a fresh signal so Connect works
			local s = make_signal()
			rawset(inst, k, s)
			return s
		end,
		__newindex = function(_, k, v)
			rawset(props, k, v)
			rawset(inst, k, v)
		end,
	})
	return inst
end

-- ---------------------------------------------------------------------------
-- datatypes
-- ---------------------------------------------------------------------------

local function vec3(x, y, z)
	x, y, z = x or 0, y or 0, z or 0
	return setmetatable({ X = x, Y = y, Z = z, Magnitude = 0,
		Unit = setmetatable({ X = 0, Y = 0, Z = 0 }, {}) }, {
		__add = function(a, b) return vec3(a.X + b.X, a.Y + b.Y, a.Z + b.Z) end,
		__sub = function(a, b) return vec3(a.X - b.X, a.Y - b.Y, a.Z - b.Z) end,
		__mul = function(a, b)
			if type(b) == "number" then return vec3(a.X * b, a.Y * b, a.Z * b) end
			return vec3(a.X * b.X, a.Y * b.Y, a.Z * b.Z)
		end,
		__tostring = function(a) return a.X .. ", " .. a.Y .. ", " .. a.Z end,
		__index = function(_, k)
			if k == "new" then return vec3 end
			return nil
		end,
	})
end

local function vec2(x, y)
	x, y = x or 0, y or 0
	return setmetatable({ X = x, Y = y, Magnitude = 0,
		Unit = setmetatable({ X = 0, Y = 0 }, {}) }, {
		__add = function(a, b) return vec2(a.X + b.X, a.Y + b.Y) end,
		__sub = function(a, b) return vec2(a.X - b.X, a.Y - b.Y) end,
		__tostring = function(a) return a.X .. ", " .. a.Y end,
		__index = function(_, k)
			if k == "new" then return vec2 end
			return nil
		end,
	})
end

local function color3(r, g, b)
	return setmetatable({ R = r or 0, G = g or 0, B = b or 0 }, {
		__tostring = function(a) return r or 0 .. ", " .. g or 0 .. ", " .. b or 0 end,
		__index = function(_, k)
			if k == "new" or k == "fromRGB" or k == "fromHSV" then return color3 end
			return nil
		end,
	})
end

local function udim2(x, y, x2, y2)
	return setmetatable({ X = x or 0, Y = y or 0,
		XOffset = x2 or 0, YOffset = y2 or 0 }, {
		__tostring = function(a)
			return "{" .. tostring(a.X) .. ", " .. tostring(a.XOffset) .. "},{" ..
				tostring(a.Y) .. ", " .. tostring(a.YOffset) .. "}"
		end,
		__index = function(_, k)
			if k == "new" or k == "fromScale" or k == "fromOffset" then return udim2 end
			return nil
		end,
	})
end

local function cframe(...)
	return setmetatable({ Position = vec3(0, 0, 0), LookVector = vec3(0, 0, -1) }, {
		__mul = function(a, b) return a end,
		__tostring = function() return "CFrame" end,
		__index = function(_, k)
			if k == "new" or k == "fromEulerAnglesXYZ" or k == "Angles"
				or k == "lookAt" or k == "fromMatrix" then
				return cframe
			end
			return nil
		end,
	})
end

-- ---------------------------------------------------------------------------
-- Enum stub
-- ---------------------------------------------------------------------------

local enum_cache = {}
local function make_enum(name)
	if enum_cache[name] then return enum_cache[name] end
	local e
	e = setmetatable({}, {
		__index = function(_, k)
			local item = setmetatable({ Name = tostring(k), Value = 0,
				EnumType = name }, {
				__tostring = function() return "Enum." .. name .. "." .. tostring(k) end,
			})
			rawset(e, k, item)
			return item
		end,
		__call = function(_, k) return make_enum(tostring(k)) end,
		__tostring = function() return "Enum." .. name end,
		GetEnumItems = function() return {} end,
	})
	enum_cache[name] = e
	return e
end

local Enum = setmetatable({}, {
	__index = function(_, k) return make_enum(tostring(k)) end,
	__call = function(_, k) return make_enum(tostring(k)) end,
})

-- ---------------------------------------------------------------------------
-- services
-- ---------------------------------------------------------------------------

local service_cache = {}
local function make_service(name)
	if service_cache[name] then return service_cache[name] end
	local svc = make_instance(name)
	-- service-specific extras
	if name == "HttpService" then
		svc.JSONEncode = function(_, t) return "{}" end
		svc.JSONDecode = function(_, s) return {} end
		svc.GetAsync = function(_, url) return "{}" end
		svc.PostAsync = function(_, url, data) return "" end
		svc.RequestAsync = function(_, opts) return { Success = false, Body = "" } end
		svc.HttpEnabled = false
	elseif name == "Players" then
		svc.LocalPlayer = make_instance("Player")
		svc.LocalPlayer.Name = "LocalPlayer"
		svc.LocalPlayer.Character = make_instance("Model")
		svc.LocalPlayer.CharacterAdded = make_signal()
		svc.LocalPlayer.CharacterRemoving = make_signal()
		svc.GetPlayers = function() return { svc.LocalPlayer } end
		svc.PlayerAdded = make_signal()
		svc.PlayerRemoving = make_signal()
	elseif name == "RunService" then
		svc.Heartbeat = make_signal()
		svc.Stepped = make_signal()
		svc.RenderStepped = make_signal()
		svc.IsStudio = function() return false end
		svc.IsServer = function() return true end
		svc.IsClient = function() return true end
	elseif name == "TweenService" then
		svc.Create = function(_, inst, info)
			return { Play = function() end, Cancel = function() end,
				Completed = make_signal() }
		end
	elseif name == "UserInputService" then
		svc.InputBegan = make_signal()
		svc.InputEnded = make_signal()
		svc.TouchEnabled = false
		svc.KeyboardEnabled = true
		svc.MouseEnabled = true
	elseif name == "CoreGui" or name == "StarterGui" then
		svc.SetCore = function(_, k, v) end
		svc.SetCoreGuiEnabled = function() end
	end
	service_cache[name] = svc
	return svc
end

local game = make_instance("DataModel")
function game:GetService(name)
	return make_service(tostring(name))
end
function game:FindService(name) return make_service(tostring(name)) end
game.Loaded = make_signal()
game.IsLoaded = function() return true end
game.Workspace = make_service("Workspace")

-- ---------------------------------------------------------------------------
-- task library
-- ---------------------------------------------------------------------------

local task_lib = {}
function task_lib.wait(t)
	-- no real waiting in the CLI; return elapsed-ish
	return t or 0
end
task_lib.spawn = function(fn, ...) return pcall(fn, ...) end
task_lib.defer = task_lib.spawn
task_lib.delay = function(t, fn, ...) return task_lib.spawn(fn, ...) end
task_lib.cancel = function() end

-- ---------------------------------------------------------------------------
-- assemble environment
-- ---------------------------------------------------------------------------

env.game = game
env.workspace = game.Workspace
env.script = make_instance("Script")
env.Instance = setmetatable({}, {
	__index = function(_, cls)
		return function(props, parent)
			local inst = make_instance(tostring(cls))
			if type(props) == "table" then
				for k, v in pairs(props) do
					inst[k] = v
				end
			end
			return inst
		end
	end,
	__call = function(_, cls) return make_instance(tostring(cls)) end,
})
env.Enum = Enum
env.task = task_lib
env.shared = {}
env._G = {}
env.Vector3 = setmetatable({}, {
	__call = function(_, ...) return vec3(...) end,
	__index = function(_, k) if k == "new" then return function(...) return vec3(...) end end return nil end,
})
env.Vector2 = setmetatable({}, {
	__call = function(_, ...) return vec2(...) end,
	__index = function(_, k) if k == "new" then return function(...) return vec2(...) end end return nil end,
})
env.Color3 = setmetatable({}, {
	__call = function(_, ...) return color3(...) end,
	__index = function(_, k)
		if k == "new" or k == "fromRGB" or k == "fromHSV" then
			return function(...) return color3(...) end
		end
		return nil
	end,
})
local function ctor(name)
	return setmetatable({}, {
		__call = function(_, ...) return { ClassName = name } end,
		__index = function(_, k)
			if k == "new" then
				return function(...) return { ClassName = name } end
			end
			return nil
		end,
	})
end
env.ColorSequence = ctor("ColorSequence")
env.ColorSequenceKeypoint = ctor("ColorSequenceKeypoint")
env.NumberSequence = ctor("NumberSequence")
env.NumberSequenceKeypoint = ctor("NumberSequenceKeypoint")
env.NumberRange = ctor("NumberRange")
env.UDim = ctor("UDim")
env.TweenInfo = ctor("TweenInfo")
env.Region3 = ctor("Region3")
env.Ray = ctor("Ray")
env.Font = ctor("Font")
env.Axes = ctor("Axes")
env.Faces = ctor("Faces")
env.Rect = ctor("Rect")
env.Path2DControlPoint = ctor("Path2DControlPoint")
env.UDim2 = setmetatable({}, {
	__call = function(_, ...) return udim2(...) end,
	__index = function(_, k)
		if k == "new" or k == "fromScale" or k == "fromOffset" then
			return function(...) return udim2(...) end
		end
		return nil
	end,
})
env.CFrame = setmetatable({}, {
	__call = function(_, ...) return cframe(...) end,
	__index = function(_, k)
		if k == "new" or k == "fromEulerAnglesXYZ" or k == "Angles"
			or k == "lookAt" or k == "fromMatrix" then
			return function(...) return cframe(...) end
		end
		return nil
	end,
})
env.BrickColor = setmetatable({}, {
	__index = function(_, k)
		return setmetatable({ Name = tostring(k) },
			{ __tostring = function() return tostring(k) end })
	end,
	__call = function(_, k)
		return setmetatable({ Name = tostring(k) },
			{ __tostring = function() return tostring(k) end })
	end,
	palette = function() return {} end,
})
env.TweenInfo = function() return {} end
env.Region3 = function() return {} end
env.Ray = function() return {} end
env.Random = setmetatable({}, {
	__index = function(_, k)
		if k == "new" then
			return function()
				return { NextInteger = function(_, a, b) return a or 0 end,
					NextNumber = function(_, a, b) return a or 0 end,
					NextVector3 = function() return vec3(0, 0, 0) end }
			end
		end
		return nil
	end,
})
env.getgenv = function() return env end
env.getrenv = function() return env end
env.identifyexecutor = function() return "sandbox", "1.0" end
env.gameLoaded = function() return true end
env.hookfunction = function(old, new) return old end
env.hookmetamethod = function() return function() end end
env.getnamecall = function() return function() end end
env.cloneref = function(ref) return ref end
env.getthreadidentity = function() return 8 end
env.setthreadidentity = function() end
env.getconnections = function() return {} end
env.request = function() return { Success = false, Body = "", StatusCode = 0 } end
env.syn = { request = env.request }
env.writefile = function() end
env.readfile = function() return "" end
env.isfile = function() return false end
env.isfolder = function() return false end
env.makefolder = function() end
env.listfiles = function() return {} end

return env
