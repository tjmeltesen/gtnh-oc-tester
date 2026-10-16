"""Implementation of all 19 GTNH 2.9 OpenComputers driver abstracts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


class DriverAbstractMixin:
    """Default stateful implementations for all 19 GTNH 2.9 driver abstracts."""

    def init_abstract_state(self) -> None:
        if not hasattr(self, "state"):
            self.state: Dict[str, Any] = {}
        self.state.setdefault("rf_energy", 50000)
        self.state.setdefault("rf_max_energy", 100000)
        self.state.setdefault("rf_is_provider", False)
        self.state.setdefault("rf_is_receiver", True)
        self.state.setdefault("aspects", {"aer": 64, "terra": 64, "ignis": 64, "aqua": 64})
        self.state.setdefault("suction_type", "aer")
        self.state.setdefault("suction_amount", 128)
        self.state.setdefault("min_suction", 0)
        self.state.setdefault("ender_frequency", 0)
        self.state.setdefault("ender_owner", "global")
        self.state.setdefault("ender_colors", (0, 0, 0))
        self.state.setdefault("reactor_heat", 0)
        self.state.setdefault("reactor_max_heat", 10000)
        self.state.setdefault("reactor_eu_output", 0.0)
        self.state.setdefault("reactor_produces_energy", True)
        self.state.setdefault("turret_armed", True)
        self.state.setdefault("turret_active", True)
        self.state.setdefault("turret_pitch", 0.0)
        self.state.setdefault("turret_yaw", 0.0)
        self.state.setdefault("turret_trusted", ["player"])
        self.state.setdefault("speech_volume", 1.0)
        self.state.setdefault("speech_messages", [])
        self.state.setdefault("gate_high_flow", 10000)
        self.state.setdefault("gate_low_flow", 0)
        self.state.setdefault("gate_override", False)
        self.state.setdefault("gate_flow_override", 0)
        self.state.setdefault("bus_config", {})
        self.state.setdefault("export_ore_filter", "")

    # 1. BaseEnergyHandler (CoFH RF)
    def getEnergyStored(self, side: Optional[int] = None) -> int:
        return int(self.state.get("rf_energy", 50000))

    def getMaxEnergyStored(self, side: Optional[int] = None) -> int:
        return int(self.state.get("rf_max_energy", 100000))

    def isEnergyProvider(self, side: Optional[int] = None) -> bool:
        return bool(self.state.get("rf_is_provider", False))

    def isEnergyReceiver(self, side: Optional[int] = None) -> bool:
        return bool(self.state.get("rf_is_receiver", True))

    # 2. BaseAspectContainer & 3. BaseEssentiaTransport (Thaumcraft)
    def getAspects(self) -> Dict[str, int]:
        return dict(self.state.get("aspects", {}))

    def getAspectCount(self, aspect: str) -> int:
        return int(self.state.get("aspects", {}).get(str(aspect).lower(), 0))

    def getEssentiaAmount(self, side: int) -> int:
        aspects = self.state.get("aspects", {})
        return sum(aspects.values()) if aspects else 0

    def getEssentiaType(self, side: int) -> str:
        aspects = self.state.get("aspects", {})
        return next(iter(aspects.keys()), "aer")

    def getMinimumSuction(self) -> int:
        return int(self.state.get("min_suction", 0))

    def getSuctionAmount(self, side: int) -> int:
        return int(self.state.get("suction_amount", 128))

    def getSuctionType(self, side: int) -> str:
        return str(self.state.get("suction_type", "aer"))

    def isConnectable(self, side: int) -> bool:
        return True

    # 4. BaseEnderStorage
    def getFrequency(self) -> int:
        return int(self.state.get("ender_frequency", 0))

    def setFrequency(self, *args: int) -> Tuple[bool, int]:
        if len(args) == 1:
            self.state["ender_frequency"] = int(args[0])
        elif len(args) >= 3:
            c1, c2, c3 = int(args[0]), int(args[1]), int(args[2])
            self.state["ender_colors"] = (c1, c2, c3)
            self.state["ender_frequency"] = ((c1 & 0xF) << 8) | ((c2 & 0xF) << 4) | (c3 & 0xF)
        return (True, int(self.state["ender_frequency"]))

    def getOwner(self) -> str:
        return str(self.state.get("ender_owner", "global"))

    def areColoursValid(self, c1: int, c2: int, c3: int) -> bool:
        return all(0 <= int(c) <= 15 for c in (c1, c2, c3))

    def getColours(self) -> Tuple[int, int, int]:
        return tuple(self.state.get("ender_colors", (0, 0, 0)))

    # 5. BaseBeeHousing (Forestry)
    def canBreed(self) -> bool:
        return bool(self.state.get("bee_can_breed", True))

    def getBeeParents(self, allele: str = "") -> List[Dict[str, Any]]:
        return list(self.state.get("bee_parents", []))

    def getDrone(self) -> Optional[Dict[str, Any]]:
        return self.state.get("bee_drone", {"name": "Forestry:beeDroneGE", "size": 1})

    def getQueen(self) -> Optional[Dict[str, Any]]:
        return self.state.get("bee_queen", {"name": "Forestry:beeQueenGE", "size": 1})

    def getErrorStates(self) -> Dict[int, str]:
        return dict(self.state.get("bee_errors", {}))

    def getHumidity(self) -> str:
        return str(self.state.get("bee_humidity", "normal"))

    def getTemperature(self) -> str:
        return str(self.state.get("bee_temperature", "normal"))

    def getIndividualInSlot(self, slot: int) -> Optional[Dict[str, Any]]:
        return self.getQueen() if int(slot) == 1 else self.getDrone()

    def listAllSpecies(self) -> List[str]:
        return list(self.state.get("bee_species", ["forestry.speciesForest", "forestry.speciesMeadows", "gregtech.speciesImperial"]))

    def getBiomeId(self) -> int:
        return int(self.state.get("bee_biome_id", 1))

    # 6. BaseReactor (IC2)
    def getHeat(self) -> int:
        return int(self.state.get("reactor_heat", 0))

    def getMaxHeat(self) -> int:
        return int(self.state.get("reactor_max_heat", 10000))

    def getReactorEUOutput(self) -> float:
        return float(self.state.get("reactor_eu_output", 0.0))

    def getReactorEnergyOutput(self) -> float:
        return float(self.state.get("reactor_eu_output", 0.0))

    def producesEnergy(self) -> bool:
        return bool(self.state.get("reactor_produces_energy", True))

    def getSlotInfo(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        slots = self.state.get("reactor_slots", {})
        return slots.get((int(x), int(y)), {"canStoreHeat": True, "heat": 0, "maxHeat": 10000})

    def getOfferedEnergy(self) -> float:
        return float(self.state.get("reactor_eu_output", 0.0))

    # 7. BaseTurretBase & 8. BaseModturTurretBase (OpenModularTurrets)
    def getMaxEnergyStorage(self) -> int:
        return int(self.state.get("rf_max_energy", 100000))

    def getCurrentEnergyStorage(self) -> int:
        return int(self.state.get("rf_energy", 50000))

    def isActive(self) -> bool:
        return bool(self.state.get("turret_active", True))

    def setArmed(self, val: bool) -> bool:
        self.state["turret_armed"] = bool(val)
        return True

    def setAttacksMobs(self, val: bool) -> bool:
        self.state["turret_attacks_mobs"] = bool(val)
        return True

    def setAttacksNeutrals(self, val: bool) -> bool:
        self.state["turret_attacks_neutrals"] = bool(val)
        return True

    def setAttacksPlayers(self, val: bool) -> bool:
        self.state["turret_attacks_players"] = bool(val)
        return True

    def isTrustedPlayer(self, name: str) -> bool:
        return str(name) in self.state.get("turret_trusted", [])

    def addTrustedPlayer(self, name: str, *args: Any) -> bool:
        trusted = self.state.setdefault("turret_trusted", [])
        if str(name) not in trusted:
            trusted.append(str(name))
        return True

    def removeTrustedPlayer(self, name: str) -> bool:
        trusted = self.state.setdefault("turret_trusted", [])
        if str(name) in trusted:
            trusted.remove(str(name))
        return True

    def getTrustedPlayers(self) -> List[str]:
        return list(self.state.get("turret_trusted", []))

    def getPitch(self) -> float:
        return float(self.state.get("turret_pitch", 0.0))

    def getYaw(self) -> float:
        return float(self.state.get("turret_yaw", 0.0))

    def moveTurret(self, yaw: float, pitch: float) -> bool:
        self.state["turret_yaw"] = float(yaw)
        self.state["turret_pitch"] = float(pitch)
        return True

    def canSeeCoord(self, x: int, y: int, z: int) -> bool:
        return True

    def fire(self) -> bool:
        return True

    def getStoredEnergy(self) -> int:
        return self.getEnergyStored()

    def getMaxEnergy(self) -> int:
        return self.getMaxEnergyStored()

    def getEnergyReceive(self) -> int:
        return 1000

    def getEnergySend(self) -> int:
        return 0

    # 9. BaseSpeech (Computronics)
    def say(self, text: str) -> bool:
        self.state.setdefault("speech_messages", []).append(str(text))
        return True

    def stop(self) -> bool:
        return True

    def isProcessing(self) -> bool:
        return False

    def setVolume(self, volume: float) -> bool:
        self.state["speech_volume"] = float(volume)
        return True

    # 10. BaseDraconicGate (Draconic Evolution)
    def getFlow(self) -> int:
        if self.state.get("gate_override", False):
            return int(self.state.get("gate_flow_override", 0))
        return int(self.state.get("gate_high_flow", 10000))

    def getSignalHighFlow(self) -> int:
        return int(self.state.get("gate_high_flow", 10000))

    def setSignalHighFlow(self, flow: int) -> None:
        self.state["gate_high_flow"] = int(flow)

    def getSignalLowFlow(self) -> int:
        return int(self.state.get("gate_low_flow", 0))

    def setSignalLowFlow(self, flow: int) -> None:
        self.state["gate_low_flow"] = int(flow)

    def setOverrideEnabled(self, state: bool) -> None:
        self.state["gate_override"] = bool(state)

    def getOverrideEnabled(self) -> bool:
        return bool(self.state.get("gate_override", False))

    def setFlowOverride(self, amount: int) -> None:
        self.state["gate_flow_override"] = int(amount)

    # 11-13. BaseExportBus, BaseImportBus, BaseStorageBus
    def getExportConfiguration(self, side: int = 0, slot: int = 1) -> Optional[Dict[str, Any]]:
        return self.state.get("bus_config", {}).get(("export", int(side), int(slot)))

    def setExportConfiguration(
        self,
        side: int = 0,
        slot: int = 1,
        db_address: Optional[str] = None,
        entry: Optional[int] = None,
    ) -> bool:
        self.state.setdefault("bus_config", {})[("export", int(side), int(slot))] = {
            "database": db_address,
            "entry": entry,
        }
        return True

    def exportIntoSlot(self, side: int, slot: int = 1) -> bool:
        return True

    def getExportSlotSize(self, side: int, slot: int = 1) -> int:
        return 64

    def getExportOreFilter(self, side: int) -> str:
        return str(self.state.get("export_ore_filter", ""))

    def setExportOreFilter(self, side: int, filter_str: str) -> bool:
        self.state["export_ore_filter"] = str(filter_str)
        return True

    def getImportConfiguration(self, side: int = 0, slot: int = 1) -> Optional[Dict[str, Any]]:
        return self.state.get("bus_config", {}).get(("import", int(side), int(slot)))

    def setImportConfiguration(
        self,
        side: int = 0,
        slot: int = 1,
        db_address: Optional[str] = None,
        entry: Optional[int] = None,
    ) -> bool:
        self.state.setdefault("bus_config", {})[("import", int(side), int(slot))] = {
            "database": db_address,
            "entry": entry,
        }
        return True

    def importFromSlot(self, side: int, slot: int = 1) -> bool:
        return True

    def getStorageConfiguration(self, side: int = 0, slot: int = 1) -> Optional[Dict[str, Any]]:
        return self.state.get("bus_config", {}).get(("storage", int(side), int(slot)))

    def setStorageConfiguration(
        self,
        side: int = 0,
        slot: int = 1,
        db_address: Optional[str] = None,
        entry: Optional[int] = None,
    ) -> bool:
        self.state.setdefault("bus_config", {})[("storage", int(side), int(slot))] = {
            "database": db_address,
            "entry": entry,
        }
        return True
