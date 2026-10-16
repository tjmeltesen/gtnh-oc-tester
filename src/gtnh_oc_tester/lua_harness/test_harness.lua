-- Busted-compatible Pure-Lua Test Harness + `mock_oc` control library for gtnh-oc-tester

local _suites = {}
local _current_suite = nil

function describe(name, fn)
  local prev = _current_suite
  local suite = {
    name = name,
    tests = {},
    before_each_fns = {},
    after_each_fns = {},
  }
  if prev then
    suite.name = prev.name .. " > " .. name
    for _, b in ipairs(prev.before_each_fns) do
      table.insert(suite.before_each_fns, b)
    end
    for _, a in ipairs(prev.after_each_fns) do
      table.insert(suite.after_each_fns, a)
    end
  end
  table.insert(_suites, suite)
  _current_suite = suite
  fn()
  _current_suite = prev
end

function before_each(fn)
  if _current_suite then
    table.insert(_current_suite.before_each_fns, fn)
  end
end

function after_each(fn)
  if _current_suite then
    table.insert(_current_suite.after_each_fns, fn)
  end
end

function it(name, fn)
  if not _current_suite then
    describe("default", function()
      it(name, fn)
    end)
    return
  end
  table.insert(_current_suite.tests, { name = name, fn = fn })
end

-- Deep table equality helper
local function _deep_equal(a, b)
  if a == b then return true end
  if type(a) ~= "table" or type(b) ~= "table" then return false end
  for k, v in pairs(a) do
    if k ~= "n" and not _deep_equal(v, b[k]) then return false end
  end
  for k, v in pairs(b) do
    if k ~= "n" and not _deep_equal(v, a[k]) then return false end
  end
  return true
end

-- Rich assert library (supports both standard Lua `assert(cond, msg)` and busted `assert.are.equal(...)`)
local _orig_assert = assert
local _assert_mt = {
  __call = function(_, cond, msg, ...)
    return _orig_assert(cond, msg, ...)
  end
}

local _assert_tbl = {}
function _assert_tbl.equals(expected, actual, msg)
  if expected ~= actual then
    error(msg or string.format("Expected %s, got %s", tostring(expected), tostring(actual)), 2)
  end
  return true
end
function _assert_tbl.same(expected, actual, msg)
  if not _deep_equal(expected, actual) then
    error(msg or string.format("Tables not deeply equal: expected %s, got %s", tostring(expected), tostring(actual)), 2)
  end
  return true
end
function _assert_tbl.is_true(val, msg)
  if val ~= true then
    error(msg or string.format("Expected true, got %s", tostring(val)), 2)
  end
  return true
end
function _assert_tbl.is_false(val, msg)
  if val ~= false then
    error(msg or string.format("Expected false, got %s", tostring(val)), 2)
  end
  return true
end
function _assert_tbl.is_nil(val, msg)
  if val ~= nil then
    error(msg or string.format("Expected nil, got %s", tostring(val)), 2)
  end
  return true
end
function _assert_tbl.is_not_nil(val, msg)
  if val == nil then
    error(msg or "Expected non-nil value, got nil", 2)
  end
  return true
end
function _assert_tbl.truthy(val, msg)
  if not val then
    error(msg or string.format("Expected truthy value, got %s", tostring(val)), 2)
  end
  return true
end
function _assert_tbl.falsy(val, msg)
  if val then
    error(msg or string.format("Expected falsy value, got %s", tostring(val)), 2)
  end
  return true
end
function _assert_tbl.has_error(fn, expected_substr, msg)
  local ok, err = pcall(fn)
  if ok then
    error(msg or "Expected function to throw an error, but it succeeded", 2)
  end
  if expected_substr and not tostring(err):find(expected_substr, 1, true) then
    error(string.format("Expected error containing '%s', got '%s'", expected_substr, tostring(err)), 2)
  end
  return true
end

_assert_tbl.are = {
  equal = _assert_tbl.equals,
  equals = _assert_tbl.equals,
  same = _assert_tbl.same,
}
_assert_tbl.is = {
  truthy = _assert_tbl.truthy,
  falsy = _assert_tbl.falsy,
}
assert = setmetatable(_assert_tbl, _assert_mt)

-- Spy helper
spy = {}
function spy.new(fn)
  fn = fn or function() end
  local s = { calls = {} }
  setmetatable(s, {
    __call = function(_, ...)
      table.insert(s.calls, {...})
      return fn(...)
    end
  })
  return s
end
function spy.on(tbl, key)
  local orig = tbl[key]
  local s = spy.new(orig)
  tbl[key] = s
  return s
end

-- Runner entrypoint invoked by Python LuaSpecRunner
function __run_registered_specs()
  local results = {}
  for _, suite in ipairs(_suites) do
    for _, t in ipairs(suite.tests) do
      local full_name = suite.name .. " :: " .. t.name
      local ok, err = xpcall(function()
        for _, b in ipairs(suite.before_each_fns) do b() end
        t.fn()
        for _, a in ipairs(suite.after_each_fns) do a() end
      end, debug.traceback)
      table.insert(results, {
        suite = suite.name,
        test = t.name,
        full_name = full_name,
        passed = ok,
        error = ok and "" or tostring(err),
      })
    end
  end
  return results
end
