"""OpenOS 28 standard libraries for the OpenComputers Lua sandbox."""

from __future__ import annotations

from typing import List


ALL_28_OPENOS_LIBS: List[str] = [
    "bit32",
    "buffer",
    "colors",
    "component",
    "computer",
    "devfs",
    "event",
    "filesystem",
    "internet",
    "io",
    "keyboard",
    "nbt",
    "note",
    "os",
    "package",
    "process",
    "robot",
    "serialization",
    "shell",
    "sides",
    "term",
    "text",
    "thread",
    "transforms",
    "tty",
    "unicode",
    "uuid",
    "vt100",
]


OPENOS_BOOTSTRAP_LUA = r"""
-- Core OpenComputers machine globals & checkArg
function checkArg(n, have, ...)
  have = type(have)
  local function check(want, ...)
    if not want then
      return false
    else
      return have == want or check(...)
    end
  end
  if not check(...) then
    local msg = string.format("bad argument #%d (%s expected, got %s)",
                              n, table.concat({...}, " or "), have)
    error(msg, 3)
  end
end

-- bit32 library (Lua 5.2 compatible)
local bit32_lib = {}
local MOD = 2^32
local function to32(x)
  return math.floor((tonumber(x) or 0) % MOD)
end
function bit32_lib.band(...)
  local args = {...}
  local r = 0xFFFFFFFF
  for i = 1, #args do
    local a, b, res, p = r, to32(args[i]), 0, 1
    for _ = 1, 32 do
      if a % 2 == 1 and b % 2 == 1 then res = res + p end
      a = math.floor(a / 2)
      b = math.floor(b / 2)
      p = p * 2
    end
    r = res
  end
  return r
end
function bit32_lib.bor(...)
  local args = {...}
  local r = 0
  for i = 1, #args do
    local a, b, res, p = r, to32(args[i]), 0, 1
    for _ = 1, 32 do
      if a % 2 == 1 or b % 2 == 1 then res = res + p end
      a = math.floor(a / 2)
      b = math.floor(b / 2)
      p = p * 2
    end
    r = res
  end
  return r
end
function bit32_lib.bxor(...)
  local args = {...}
  local r = 0
  for i = 1, #args do
    local a, b, res, p = r, to32(args[i]), 0, 1
    for _ = 1, 32 do
      if (a % 2) ~= (b % 2) then res = res + p end
      a = math.floor(a / 2)
      b = math.floor(b / 2)
      p = p * 2
    end
    r = res
  end
  return r
end
function bit32_lib.bnot(x)
  return (MOD - 1) - to32(x)
end
function bit32_lib.lshift(x, disp)
  x = to32(x)
  disp = math.floor(tonumber(disp) or 0)
  if disp < 0 then return bit32_lib.rshift(x, -disp) end
  if disp >= 32 then return 0 end
  return to32(x * (2 ^ disp))
end
function bit32_lib.rshift(x, disp)
  x = to32(x)
  disp = math.floor(tonumber(disp) or 0)
  if disp < 0 then return bit32_lib.lshift(x, -disp) end
  if disp >= 32 then return 0 end
  return math.floor(x / (2 ^ disp))
end
function bit32_lib.arshift(x, disp)
  x = to32(x)
  disp = math.floor(tonumber(disp) or 0)
  if disp < 0 then return bit32_lib.lshift(x, -disp) end
  if x < 0x80000000 then return bit32_lib.rshift(x, disp) end
  if disp >= 32 then return 0xFFFFFFFF end
  local shifted = math.floor(x / (2 ^ disp))
  local mask = (MOD - 1) - (2 ^ (32 - disp) - 1)
  return bit32_lib.bor(shifted, mask)
end
function bit32_lib.btest(...)
  return bit32_lib.band(...) ~= 0
end
function bit32_lib.extract(n, field, width)
  width = width or 1
  return bit32_lib.band(bit32_lib.rshift(n, field), 2^width - 1)
end
function bit32_lib.replace(n, v, field, width)
  width = width or 1
  local mask = (2^width - 1) * (2^field)
  return bit32_lib.bor(bit32_lib.band(n, bit32_lib.bnot(mask)), bit32_lib.band(v * (2^field), mask))
end
function bit32_lib.lrotate(x, disp)
  disp = disp % 32
  x = to32(x)
  return bit32_lib.bor(bit32_lib.lshift(x, disp), bit32_lib.rshift(x, 32 - disp))
end
function bit32_lib.rrotate(x, disp)
  return bit32_lib.lrotate(x, -disp)
end
bit32 = bit32_lib
package.loaded["bit32"] = bit32_lib

-- unicode library
local unicode_lib = {}
function unicode_lib.len(s) return __oc_bridge.unicode_len(tostring(s or "")) end
function unicode_lib.sub(s, i, j) return __oc_bridge.unicode_sub(tostring(s or ""), i or 1, j) end
function unicode_lib.lower(s) return __oc_bridge.unicode_lower(tostring(s or "")) end
function unicode_lib.upper(s) return __oc_bridge.unicode_upper(tostring(s or "")) end
function unicode_lib.reverse(s) return __oc_bridge.unicode_reverse(tostring(s or "")) end
function unicode_lib.char(...) return __oc_bridge.unicode_char(...) end
function unicode_lib.wlen(s) return __oc_bridge.unicode_wlen(tostring(s or "")) end
function unicode_lib.wtrunc(s, n) return __oc_bridge.unicode_wtrunc(tostring(s or ""), n or 0) end
function unicode_lib.charWidth(s) return __oc_bridge.unicode_char_width(tostring(s or "")) end
function unicode_lib.isWide(s) return __oc_bridge.unicode_char_width(tostring(s or "")) > 1 end
unicode = unicode_lib
package.loaded["unicode"] = unicode_lib

-- computer library
local computer_lib = {}
function computer_lib.uptime() return __oc_bridge.uptime() end
function computer_lib.address() return __oc_bridge.computer_address() end
function computer_lib.tmpAddress() return __oc_bridge.tmp_address() end
function computer_lib.freeMemory() return __oc_bridge.free_memory() end
function computer_lib.totalMemory() return __oc_bridge.total_memory() end
function computer_lib.energy() return __oc_bridge.energy() end
function computer_lib.maxEnergy() return __oc_bridge.max_energy() end
function computer_lib.isRobot() return __oc_bridge.is_robot() end
function computer_lib.beep(freq, dur) return __oc_bridge.beep(freq or 440, dur or 0.1) end
function computer_lib.pushSignal(name, ...) return __oc_bridge.push_signal(name, ...) end
function computer_lib.pullSignal(timeout)
  local res = __oc_bridge.pull_signal(timeout)
  if type(res) == "table" then
    return table.unpack(res, 1, res.n or #res)
  end
  return res
end
function computer_lib.users() return "player" end
function computer_lib.addUser(name) return true end
function computer_lib.removeUser(name) return true end
function computer_lib.getBootAddress() return __oc_bridge.root_fs_address() end
function computer_lib.setBootAddress(addr) return true end
function computer_lib.getArchitecture() return "Lua 5.3" end
function computer_lib.getArchitectures() return {"Lua 5.2", "Lua 5.3"} end
function computer_lib.setArchitecture(arch) return false end
function computer_lib.shutdown(reboot) return __oc_bridge.shutdown(reboot or false) end
computer = computer_lib
package.loaded["computer"] = computer_lib

-- os library extensions
os.sleep = function(seconds)
  __oc_bridge.sleep(seconds or 0.05)
end
local _orig_os_clock = os.clock
os.clock = function()
  return __oc_bridge.uptime()
end
local _env_vars = {
  PATH = "/bin:/usr/bin:/home/bin:.",
  PWD = "/home",
  HOME = "/home",
  SHELL = "/bin/sh.lua",
  TMP = "/tmp",
  TMPDIR = "/tmp",
}
os.getenv = function(varname)
  if varname == nil then return _env_vars end
  return _env_vars[tostring(varname)]
end
os.setenv = function(varname, value)
  _env_vars[tostring(varname)] = value
  return value
end
package.loaded["os"] = os

-- event library
local event_lib = {}
local function _unpack_pull(res)
  if type(res) == "table" then
    return table.unpack(res, 1, res.n or #res)
  end
  return res
end
function event_lib.pull(...)
  local args = {...}
  if #args == 0 then
    return _unpack_pull(__oc_bridge.pull_signal(nil, nil))
  end
  if type(args[1]) == "number" then
    return _unpack_pull(__oc_bridge.pull_signal(args[1], table.unpack(args, 2)))
  else
    return _unpack_pull(__oc_bridge.pull_signal(nil, table.unpack(args, 1)))
  end
end
function event_lib.pullMultiple(...)
  local filters = {...}
  local timeout = nil
  if type(filters[1]) == "number" then
    timeout = table.remove(filters, 1)
  end
  return _unpack_pull(__oc_bridge.pull_signal(timeout, nil))
end
function event_lib.push(name, ...)
  return __oc_bridge.push_signal(name, ...)
end
function event_lib.listen(name, callback)
  checkArg(1, name, "string")
  checkArg(2, callback, "function")
  return __oc_bridge.listen(name, callback)
end
function event_lib.ignore(name, callback)
  checkArg(1, name, "string")
  checkArg(2, callback, "function")
  return __oc_bridge.ignore(name, callback)
end
function event_lib.timer(interval, callback, times)
  checkArg(1, interval, "number")
  checkArg(2, callback, "function")
  checkArg(3, times, "number", "nil")
  return __oc_bridge.timer(interval, callback, times or 1)
end
function event_lib.cancel(timerId)
  checkArg(1, timerId, "number")
  return __oc_bridge.cancel_timer(timerId)
end
function event_lib.onError(message)
  return false
end
package.loaded["event"] = event_lib

-- filesystem library
local fs_lib = {}
function fs_lib.canonical(path) return __oc_bridge.fs_canonical(path or "/") end
function fs_lib.segments(path) return __oc_bridge.fs_segments(path or "/") end
function fs_lib.concat(...) return __oc_bridge.fs_concat(...) end
function fs_lib.path(path) return __oc_bridge.fs_path(path or "/") end
function fs_lib.name(path) return __oc_bridge.fs_name(path or "/") end
function fs_lib.exists(path) return __oc_bridge.fs_exists(path) end
function fs_lib.isDirectory(path) return __oc_bridge.fs_is_directory(path) end
function fs_lib.makeDirectory(path) return __oc_bridge.fs_make_directory(path) end
function fs_lib.size(path) return __oc_bridge.fs_size(path) end
function fs_lib.lastModified(path) return __oc_bridge.fs_last_modified(path) end
function fs_lib.remove(path) return __oc_bridge.fs_remove(path) end
function fs_lib.rename(oldPath, newPath) return __oc_bridge.fs_rename(oldPath, newPath) end
function fs_lib.copy(fromPath, toPath) return __oc_bridge.fs_copy(fromPath, toPath) end
function fs_lib.list(path)
  local items = __oc_bridge.fs_list(path or "/")
  local idx = 0
  return function()
    idx = idx + 1
    return items[idx]
  end
end
function fs_lib.open(path, mode)
  local res = __oc_bridge.fs_open(path, mode or "r")
  if type(res) == "table" then
    return res[1], res[2]
  end
  return res
end
function fs_lib.mounts()
  local m = {
    {__oc_bridge.get_fs_proxy("/"), "/"},
    {__oc_bridge.get_fs_proxy("/tmp"), "/tmp"},
  }
  local idx = 0
  return function()
    idx = idx + 1
    if m[idx] then return m[idx][1], m[idx][2] end
  end
end
function fs_lib.get(path)
  return __oc_bridge.get_fs_proxy(path or "/"), "/"
end
function fs_lib.mount(fs, path) return true end
function fs_lib.umount(fsOrPath) return true end
function fs_lib.isAutorunEnabled() return false end
function fs_lib.setAutorunEnabled(val) return true end
package.loaded["filesystem"] = fs_lib

-- io library backed by VFS
local io_lib = {}
function io_lib.open(path, mode)
  return fs_lib.open(path, mode or "r")
end
function io_lib.lines(path)
  local f, err = io_lib.open(path, "r")
  if not f then error(err or ("cannot open file: " .. tostring(path))) end
  return function()
    local line = f:read("*l")
    if line == nil then f:close() end
    return line
  end
end
function io_lib.write(...)
  local parts = {}
  for i = 1, select("#", ...) do
    parts[#parts + 1] = tostring(select(i, ...))
  end
  __oc_bridge.term_write(table.concat(parts), false)
  return true
end
function io_lib.read(fmt)
  return __oc_bridge.term_read()
end
function io_lib.flush() return true end
io = setmetatable(io_lib, {__index = _G.io or {}})
package.loaded["io"] = io

-- tty & term libraries
local tty_lib = {}
function tty_lib.clear() return __oc_bridge.term_clear() end
function tty_lib.clearLine() return __oc_bridge.term_clear_line() end
function tty_lib.getCursor()
  local res = __oc_bridge.term_get_cursor()
  if type(res) == "table" then return res[1], res[2] end
  return res
end
function tty_lib.setCursor(col, row) return __oc_bridge.term_set_cursor(col, row) end
function tty_lib.getViewport()
  local res = __oc_bridge.term_get_viewport()
  if type(res) == "table" then return table.unpack(res, 1, 6) end
  return res
end
function tty_lib.isAvailable() return true end
function tty_lib.gpu() return component.gpu end
function tty_lib.screen() return component.screen and component.screen.address or nil end
package.loaded["tty"] = tty_lib

local term_lib = setmetatable({internal = {}}, {__index = tty_lib})
function term_lib.write(value, wrap)
  return __oc_bridge.term_write(tostring(value or ""), wrap ~= false)
end
function term_lib.read(history, dobreak, hint, pwchar)
  return __oc_bridge.term_read()
end
function term_lib.getCursorBlink() return false end
function term_lib.setCursorBlink(enabled) end
function term_lib.pull(...) return event_lib.pull(...) end
function term_lib.bind(gpu) end
package.loaded["term"] = term_lib

-- shell library
local shell_lib = {}
function shell_lib.getWorkingDirectory() return __oc_bridge.get_cwd() end
function shell_lib.setWorkingDirectory(dir) return __oc_bridge.set_cwd(dir) end
function shell_lib.getPath() return os.getenv("PATH") end
function shell_lib.setPath(value) os.setenv("PATH", value) end
function shell_lib.resolve(path, ext)
  return __oc_bridge.fs_canonical(path)
end
function shell_lib.parse(...)
  local args = {}
  local opts = {}
  for i = 1, select("#", ...) do
    local a = tostring(select(i, ...))
    if a:sub(1, 2) == "--" then
      local k, v = a:match("^%-%-([^=]+)=(.*)$")
      if k then opts[k] = v else opts[a:sub(3)] = true end
    elseif a:sub(1, 1) == "-" and #a > 1 then
      for c in a:sub(2):gmatch(".") do opts[c] = true end
    else
      table.insert(args, a)
    end
  end
  return args, opts
end
function shell_lib.execute(cmd, env, ...)
  return true
end
package.loaded["shell"] = shell_lib

-- thread library (coroutine-based OpenOS thread handle)
local thread_lib = {}
function thread_lib.create(fn, ...)
  checkArg(1, fn, "function")
  local args = {...}
  local co = coroutine.create(function()
    return fn(table.unpack(args))
  end)
  local status_str = "running"
  local ok, err = coroutine.resume(co)
  if coroutine.status(co) == "dead" then
    status_str = "dead"
  end
  local handle = {}
  function handle:status() return status_str end
  function handle:suspend() status_str = "suspended"; return true end
  function handle:resume()
    if coroutine.status(co) ~= "dead" then
      status_str = "running"
      coroutine.resume(co)
      if coroutine.status(co) == "dead" then status_str = "dead" end
    end
    return true
  end
  function handle:kill() status_str = "dead"; return true end
  function handle:join(timeout)
    while coroutine.status(co) ~= "dead" and status_str ~= "dead" do
      local ok2 = coroutine.resume(co)
      if not ok2 or coroutine.status(co) == "dead" then
        status_str = "dead"
        break
      end
    end
    return true
  end
  function handle:detach() return self end
  return handle
end
function thread_lib.waitForAll(threads, timeout)
  for _, t in ipairs(threads or {}) do
    if t and t.join then t:join(timeout) end
  end
  return true
end
function thread_lib.waitForAny(threads, timeout)
  for _, t in ipairs(threads or {}) do
    if t and t.join then t:join(timeout); break end
  end
  return true
end
function thread_lib.current()
  return {status = function() return "running" end}
end
package.loaded["thread"] = thread_lib

-- keyboard library
local keyboard_lib = {
  keys = {
    ["1"] = 0x02, ["2"] = 0x03, ["3"] = 0x04, ["4"] = 0x05,
    a = 0x1E, b = 0x30, c = 0x2E, d = 0x20, e = 0x12, f = 0x21,
    q = 0x10, r = 0x13, s = 0x1F, w = 0x11, enter = 0x1C, space = 0x39,
    up = 0xC8, down = 0xD0, left = 0xCB, right = 0xCD,
    lcontrol = 0x1D, lshift = 0x2A, lmenu = 0x38, tab = 0x0F, back = 0x0E,
  },
  pressedChars = {},
  pressedCodes = {},
}
function keyboard_lib.isAltDown() return false end
function keyboard_lib.isControl(char) return type(char) == "number" and (char < 0x20 or (char >= 0x7F and char <= 0x9F)) end
function keyboard_lib.isControlDown() return false end
function keyboard_lib.isKeyDown(charOrCode) return false end
function keyboard_lib.isShiftDown() return false end
package.loaded["keyboard"] = keyboard_lib

-- internet library
local internet_lib = {}
function internet_lib.request(url, data, headers, method)
  local body = __oc_bridge.http_request(url, data, headers, method)
  local done = false
  return setmetatable({
    read = function(_, n)
      if done then return nil end
      done = true
      return body
    end,
    response = function() return 200, "OK", {} end,
    finishConnect = function() return true end,
    close = function() done = true end,
  }, {
    __call = function()
      if done then return nil end
      done = true
      return body
    end
  })
end
function internet_lib.socket(address, port)
  return {read = function() return "" end, write = function(_, d) return #tostring(d) end, close = function() end}
end
function internet_lib.open(address, port)
  return internet_lib.socket(address, port)
end
package.loaded["internet"] = internet_lib

-- robot library (wraps component.robot)
local robot_lib = {}
setmetatable(robot_lib, {
  __index = function(_, k)
    local r = component.isAvailable("robot") and component.robot or nil
    if r and r[k] then
      return function(...) return r[k](...) end
    end
    return function() return false, "robot not available" end
  end
})
function robot_lib.name()
  return component.isAvailable("robot") and component.robot.name() or "robot"
end
function robot_lib.level()
  return component.isAvailable("experience") and component.experience.level() or 0
end
package.loaded["robot"] = robot_lib

-- process, buffer, devfs
package.loaded["process"] = {
  info = function() return {path = "/home/main.lua", env = _env_vars, data = {handles = {}}} end,
  load = function(path) return loadfile(path) end,
  findProcess = function() return nil end,
}
package.loaded["buffer"] = {
  new = function(mode, stream) return stream end,
}
package.loaded["devfs"] = {
  create = function() return true end,
  register = function() return true end,
}
"""
