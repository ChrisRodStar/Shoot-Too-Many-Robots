# Findings from the shipped image

Facts recovered while preparing the decompilation. They are evidence, not
guesses, and they shape what can be named cheaply.

## Build

- PE32, i386, image base `0x00400000`, entry `0x0083e167`.
- Timestamp `2012-04-09` (Unix `1334071689`).
- Imports `MSVCR90.dll` and `MSVCP90.dll`: **Visual C++ 2008 (VC9)**.
- Full PDB path retained, but no PDB payload:
  `c:\Demiurge1683\Sandbox\SomervillePC\Dev\Somerville\Binaries\PC\Ship\ShootManyRobots.pdb`.
- Internal project/codename: **Somerville** / **duckduck**, with RakNet sources
  under `C:\Demiurge1683\Sandbox\SomervillePC\Dev\External\RakNet_360_PS3-4.033`.
- Section layout: `.text`, `.rdata`, `.data`, `.rsrc`, `.reloc`, `.bind`.
  `.bind` is a Steam DRM/packer stub (6 functions) and is out of scope.

## Names that are actually recoverable

| Source | Count | What it gives |
| --- | --- | --- |
| PE exports | 200 | Seoul Engine API: `GSystem`, `GMatrix2D/3D`, `GThread`, `GWaitable`, `GSysFile`, `GImage`, `GBufferedFile`, … |
| RTTI type descriptors | 432 unique Seoul class names (527 vtable classes) | class names, template instantiations, callback types, vtable class identity |
| `Class::Method` strings | 142 | the RPC surface and named callbacks (see caveat below) |
| UI/script keys | thousands | `$lobby_mode_invite`, `lobby_quickmatch_searching`, `$helpbar_back`, … |
| Assert source paths | 15 strings | only RakNet/PhysX headers; game source paths were stripped |
| PDB | 0 | path only, no symbols |

Ghidra applies the 200 exports and RTTI names to 513 functions. A second pass
(`tools/analyze_vtables.py`) recovers **608 vtables across 527 classes**, and
2,850 unnamed virtual slot targets are labelled `Class::vfunc_N`; 43,095
functions remain placeholders. Those labels are locators, not source names.

### RTTI class families

The RTTI descriptors expose the engine/game architecture without symbols:

- **Engine core**: `GSystem`, `GMemoryHeap`, `GSysAlloc*`, `GThread`, `GMutex`,
  `GEvent`, `GSemaphore`, `GWaitable`, `GFile`, `GBufferedFile`, `GImage`.
- **Rendering**: `GMatrix2D/3D`, `GColor`, `GRender*`, `GFx*` (Scaleform),
  `FxFactory` classes, `TMaterialParameter<...>`.
- **Networking**: `SomervilleGameApp`, `SomervilleMatchmaker`,
  `SomervilleMatchmakerSteam`, `SteamSession`, `SessionInterface`,
  `Lobby2Client_Steam_Impl`, `RakPeer`, `RakNetGUID`, RPC3 binders.
- **Gameplay**: `Player`, `Character`, `Robot`, `Weapon`, `Projectile`,
  `ComboInfo`, `DamageInfo`, `Pickup`, `NutPickup`, `SpawnComponent`,
  `SomervilleMovementComponent`, `NetworkAnimSyncComponent`,
  `HazardComponent`, `RoomBossBaseComponent`, `KillboxWaveEventComponent`,
  `PlayerInteractionComponent`, `EnableDisableCollisionEventComponent`,
  `CaravanGameMode`, `Campfire_*` FX classes.
- **UI/front-end**: `GUIScreen*` (`_Lobby`, `_Confirmation`, `Modal`),
  `SomervilleTitleManager*`, leaderboard and achievement managers.
- **Platform**: `SomervillePC`, `EnginePCSteam`, Steam callback/result templates.

### Network RPC method names

These strings describe the RPC surface, but in this image the pool is
**unreferenced**: no pointer or immediate in `.text`/`.rdata`/`.data` targets
them. They are almost certainly a debug/registration name pool whose entries
are looked up by ID or hash at runtime. They are useful as a protocol map, but
they cannot be tied to handlers by a simple xref. Recovering the mapping needs
the RPC dispatch table itself:

```text
SomervilleGameApp::ClientLevelStarted
SomervilleGameApp::ClientLevelCompleted
SomervilleGameApp::RPC_InternalClientReceivePlayer
SomervilleGameApp::ClientExitToLobby
SomervilleGameApp::ServerSwitchToLevel
SomervilleGameApp::ClientCreateDrop
SomervilleGameApp::ServerReceivePlayerProgress
SomervilleGameApp::AddSuccessfulInviter
SomervilleGameApp::ClientWaitInProgress
SomervilleGameApp::ClientTriggerEvent
SomervilleGameApp::ClientReceivePlayerCountForGameplayInitialization
SomervilleGameApp::ClientReceiveQuickmatchListName
SomervilleGameApp::ClientReceiveQuickmatchCountdownTime
SomervilleGameApp::ServerResendWeaponInformation
SomervilleGameApp::ClientUpdateQoSConnections
SomervilleGameApp::ServerReceiveAverageQoSPing
SomervilleGameApp::ClientReceiveHostMigrationTarget
SomervilleGameApp::ServerConfirmHostMigrationTargetReceived
SomervilleGameApp::ClientReceiveHostMigrationLevel
SomervilleGameApp::ServerConfirmHostMigrationLevel
SomervilleGameApp::ServerResendDynamicRobotSpawnInformation
SomervilleGameApp::ServerResendPickupRPGItemOrWeapon
SomervilleGameApp::ClientReceiveUpdatedPlayerID
```

The multiplayer model is RakNet RPC3 + Lobby2 over Steam: quickmatch,
host migration, QoS pings, level switching, player progress and state
resends. That is consistent with the game's co-op focus.

## Middleware

- **Scaleform GFx** (`GFxLoader`, `GFxSprite`, `GFxResource`, `gfxVersion`) for
  the interface. UI keys like `$lobby_start_game` are Scaleform/Seoul script
  bindings, not C++ strings.
- **FMOD** (`fmodex.dll`, `fmod_event.dll`): `FMOD::System`, `FMOD::Event*`,
  DSP and 3D settings; the parent runtime already recompiles these.
- **PhysX 2.8.4** (`NxUserEntityReport`, NXU tinyxml paths): physics.
- **RakNet 4.033** plus RPC3 and Lobby2: networking.
- **Steamworks** (`steam_api.dll`): sessions, leaderboards, achievements,
  cloud, overlay, Push-to-Talk.
- **boost** (`bind_t`, `fusion`, `error_info_injector`): RPC argument binding.

## Why this matters for the tree

- The 432 RTTI classes can be turned into a class map and used to name vtable
  slots and constructors without guessing.
- The 142 `Class::Method` strings are strong `high`-confidence names once the
  registration table is located (Phase 1 of the roadmap).
- Strings are already indexed per function (`build/game/strings.tsv`), so a
  reviewer can search for a UI key or assert message and jump to the code that
  uses it.
- The absence of game source paths means bank grouping is mechanical, and
  naming must come from RTTI, tables, and behaviour rather than debug metadata.
