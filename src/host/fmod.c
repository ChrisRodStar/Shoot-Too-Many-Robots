#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "shims.h"

// Native FMOD Ex / FMOD Designer stubs for fmodex.dll and fmod_event.dll.
// All C++ methods in these DLLs use __stdcall (this at [ESP+4], callee cleanup).

static uint32_t fmod_obj(uint32_t *slot) {
    if (!*slot) {
        *slot = gmalloc(64);
        if (*slot) memset(MEM + *slot, 0, 64);
    }
    return *slot;
}

static uint32_t g_event_system;
static uint32_t g_fmod_system;
static uint32_t g_music_system;
static uint32_t g_event_project;
static uint32_t g_event_group;
static uint32_t g_event_category;
static uint32_t g_event;
static uint32_t g_event_param;
static uint32_t g_dsp;
static uint32_t g_channel;
static uint32_t g_empty_str;

static uint32_t empty_cstr(void) {
    if (!g_empty_str) {
        g_empty_str = gmalloc(4);
        if (g_empty_str) memset(MEM + g_empty_str, 0, 4);
    }
    return g_empty_str;
}

#define FMOD_STUB(name, nargs) SHIM(name) { RET(c, 0, (nargs)); }

// ---- fmodex.dll ----
FMOD_STUB(fmodex_Memory_Initialize, 6)
FMOD_STUB(fmodex_System_setOutput, 2)
FMOD_STUB(fmodex_System_setFileSystem, 8)
FMOD_STUB(fmodex_System_set3DSettings, 4)

SHIM(fmodex_System_getVersion) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0x00043400u);
    RET(c, 0, 2);
}

SHIM(fmodex_System_getNumDrivers) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 1);
    RET(c, 0, 2);
}

FMOD_STUB(fmodex_System_setSoftwareFormat, 6)
FMOD_STUB(fmodex_System_setDSPBufferSize, 3)
FMOD_STUB(fmodex_System_setSpeakerMode, 2)
SHIM(fmodex_System_getDriverInfo) {
    uint32_t name = ARG(c, 2), namelen = ARG(c, 3), guid = ARG(c, 4);
    if (name && namelen) {
        const char *drv = "Primary Sound Driver";
        size_t n = strlen(drv);
        if (n >= namelen) n = namelen - 1;
        memcpy(MEM + name, drv, n);
        MEM[name + n] = 0;
    }
    if (guid) memset(MEM + guid, 0, 16);
    RET(c, 0, 5);
}

SHIM(fmodex_System_getDriverCaps) {
    uint32_t caps = ARG(c, 2), minf = ARG(c, 3), maxf = ARG(c, 4), smode = ARG(c, 5);
    if (caps) P32(caps, 0);
    if (minf) P32(minf, 48000);
    if (maxf) P32(maxf, 48000);
    if (smode) P32(smode, 2);
    RET(c, 0, 6);
}

FMOD_STUB(fmodex_System_getMemoryInfo, 5)

SHIM(fmodex_System_createDSP) {
    uint32_t out = ARG(c, 2);
    if (out) P32(out, fmod_obj(&g_dsp));
    RET(c, 0, 3);
}

SHIM(fmodex_System_playDSP) {
    uint32_t out = ARG(c, 4);
    if (out) P32(out, fmod_obj(&g_channel));
    RET(c, 0, 5);
}

FMOD_STUB(fmodex_DSP_release, 1)
FMOD_STUB(fmodex_DSP_setDefaults, 5)

SHIM(fmodex_DSP_getDefaults) {
    for (int i = 1; i <= 4; i++) {
        uint32_t p = ARG(c, i);
        if (p) P32(p, 0);
    }
    RET(c, 0, 5);
}

SHIM(fmodex_DSP_getInfo) {
    uint32_t name = ARG(c, 1);
    if (name) MEM[name] = 0;
    for (int i = 2; i <= 5; i++) {
        uint32_t p = ARG(c, i);
        if (p) P32(p, 0);
    }
    RET(c, 0, 6);
}

SHIM(fmodex_DSP_getUserData) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

// ---- fmod_event.dll ----
SHIM(fmod_EventSystem_Create) {
    uint32_t out = ARG(c, 0);
    if (out) P32(out, fmod_obj(&g_event_system));
    RET(c, 0, 1);
}

FMOD_STUB(fmod_Event_SetCallback, 3)
FMOD_STUB(fmod_EventSystem_init, 5)
FMOD_STUB(fmod_EventSystem_release, 1)
FMOD_STUB(fmod_EventSystem_unload, 1)
FMOD_STUB(fmod_EventSystem_update, 1)
FMOD_STUB(fmod_EventSystem_setMediaPath, 2)
SHIM(fmod_EventSystem_load) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event_project));
    RET(c, 0, 4);
}
FMOD_STUB(fmod_EventSystem_set3DNumListeners, 2)
FMOD_STUB(fmod_EventSystem_set3DListenerAttributes, 6)

SHIM(fmod_EventSystem_getSystemObject) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, fmod_obj(&g_fmod_system));
    RET(c, 0, 2);
}

SHIM(fmod_EventSystem_getMusicSystem) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, fmod_obj(&g_music_system));
    RET(c, 0, 2);
}

SHIM(fmod_EventSystem_getProject) {
    uint32_t out = ARG(c, 2);
    if (out) P32(out, fmod_obj(&g_event_project));
    RET(c, 0, 3);
}

SHIM(fmod_EventSystem_getNumProjects) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

SHIM(fmod_EventSystem_getCategory) {
    uint32_t out = ARG(c, 2);
    if (out) P32(out, fmod_obj(&g_event_category));
    RET(c, 0, 3);
}

SHIM(fmod_EventSystem_getEvent) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event));
    RET(c, 0, 4);
}

SHIM(fmod_EventSystem_getEventByGUID) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event));
    RET(c, 0, 4);
}

FMOD_STUB(fmod_EventProject_release, 1)
FMOD_STUB(fmod_EventProject_getInfo, 2)

SHIM(fmod_EventProject_getGroupByIndex) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event_group));
    RET(c, 0, 4);
}

SHIM(fmod_EventProject_getNumGroups) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

FMOD_STUB(fmod_EventGroup_freeEventData, 3)

SHIM(fmod_EventGroup_getGroupByIndex) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event_group));
    RET(c, 0, 4);
}

SHIM(fmod_EventGroup_getNumGroups) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

SHIM(fmod_EventGroup_getEventByIndex) {
    uint32_t out = ARG(c, 3);
    if (out) P32(out, fmod_obj(&g_event));
    RET(c, 0, 4);
}

SHIM(fmod_EventGroup_getNumEvents) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

FMOD_STUB(fmod_EventCategory_setVolume, 2)
FMOD_STUB(fmod_EventCategory_setPaused, 2)
FMOD_STUB(fmod_MusicSystem_loadSoundData, 3)

SHIM(fmod_Event_getInfo) {
    uint32_t idx = ARG(c, 1), name = ARG(c, 2);
    if (idx) P32(idx, 0);
    if (name) P32(name, empty_cstr());
    RET(c, 0, 4);
}

FMOD_STUB(fmod_Event_start, 1)
FMOD_STUB(fmod_Event_stop, 2)
FMOD_STUB(fmod_Event_setPaused, 2)

SHIM(fmod_Event_getParameter) {
    uint32_t out = ARG(c, 2);
    if (out) P32(out, fmod_obj(&g_event_param));
    RET(c, 0, 3);
}

SHIM(fmod_Event_getParameterByIndex) {
    uint32_t out = ARG(c, 2);
    if (out) P32(out, fmod_obj(&g_event_param));
    RET(c, 0, 3);
}

FMOD_STUB(fmod_Event_getPropertyByIndex, 4)
FMOD_STUB(fmod_Event_setPropertyByIndex, 4)
FMOD_STUB(fmod_Event_setCallback, 3)
FMOD_STUB(fmod_Event_set3DAttributes, 4)

SHIM(fmod_Event_getState) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, 0);
    RET(c, 0, 2);
}

SHIM(fmod_Event_getParentGroup) {
    uint32_t out = ARG(c, 1);
    if (out) P32(out, fmod_obj(&g_event_group));
    RET(c, 0, 2);
}

SHIM(fmod_EventParameter_getInfo) {
    uint32_t idx = ARG(c, 1), name = ARG(c, 2);
    if (idx) P32(idx, 0);
    if (name) P32(name, empty_cstr());
    RET(c, 0, 3);
}

FMOD_STUB(fmod_EventParameter_setValue, 2)
FMOD_STUB(fmod_EventParameter_keyOff, 1)

typedef struct {
    const char *name;
    ShimFn fn;
} FmodShimEntry;

static const FmodShimEntry fmodex_shims[] = {
    {"FMOD_Memory_Initialize", fmodex_Memory_Initialize_},
    {"?setOutput@System@FMOD@@QAG?AW4FMOD_RESULT@@W4FMOD_OUTPUTTYPE@@@Z", fmodex_System_setOutput_},
    {"?getNumDrivers@System@FMOD@@QAG?AW4FMOD_RESULT@@PAH@Z", fmodex_System_getNumDrivers_},
    {"?setFileSystem@System@FMOD@@QAG?AW4FMOD_RESULT@@P6G?AW43@PBDHPAIPAPAX2@ZP6G?AW43@PAX4@ZP6G?AW43@44I14@ZP6G?AW43@4I4@ZP6G?AW43@PAUFMOD_ASYNCREADINFO@@4@Z5H@Z", fmodex_System_setFileSystem_},
    {"?set3DSettings@System@FMOD@@QAG?AW4FMOD_RESULT@@MMM@Z", fmodex_System_set3DSettings_},
    {"?getVersion@System@FMOD@@QAG?AW4FMOD_RESULT@@PAI@Z", fmodex_System_getVersion_},
    {"?setSoftwareFormat@System@FMOD@@QAG?AW4FMOD_RESULT@@HW4FMOD_SOUND_FORMAT@@HHW4FMOD_DSP_RESAMPLER@@@Z", fmodex_System_setSoftwareFormat_},
    {"?setDSPBufferSize@System@FMOD@@QAG?AW4FMOD_RESULT@@IH@Z", fmodex_System_setDSPBufferSize_},
    {"?setSpeakerMode@System@FMOD@@QAG?AW4FMOD_RESULT@@W4FMOD_SPEAKERMODE@@@Z", fmodex_System_setSpeakerMode_},
    {"?getDriverInfo@System@FMOD@@QAG?AW4FMOD_RESULT@@HPADHPAUFMOD_GUID@@@Z", fmodex_System_getDriverInfo_},
    {"?getDriverCaps@System@FMOD@@QAG?AW4FMOD_RESULT@@HPAIPAH1PAW4FMOD_SPEAKERMODE@@@Z", fmodex_System_getDriverCaps_},
    {"?getMemoryInfo@System@FMOD@@QAG?AW4FMOD_RESULT@@IIPAIPAUFMOD_MEMORY_USAGE_DETAILS@@@Z", fmodex_System_getMemoryInfo_},
    {"?createDSP@System@FMOD@@QAG?AW4FMOD_RESULT@@PAUFMOD_DSP_DESCRIPTION@@PAPAVDSP@2@@Z", fmodex_System_createDSP_},
    {"?playDSP@System@FMOD@@QAG?AW4FMOD_RESULT@@W4FMOD_CHANNELINDEX@@PAVDSP@2@_NPAPAVChannel@2@@Z", fmodex_System_playDSP_},
    {"?release@DSP@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmodex_DSP_release_},
    {"?setDefaults@DSP@FMOD@@QAG?AW4FMOD_RESULT@@MMMH@Z", fmodex_DSP_setDefaults_},
    {"?getDefaults@DSP@FMOD@@QAG?AW4FMOD_RESULT@@PAM00PAH@Z", fmodex_DSP_getDefaults_},
    {"?getInfo@DSP@FMOD@@QAG?AW4FMOD_RESULT@@PADPAIPAH22@Z", fmodex_DSP_getInfo_},
    {"?getUserData@DSP@FMOD@@QAG?AW4FMOD_RESULT@@PAPAX@Z", fmodex_DSP_getUserData_},
};

static const FmodShimEntry fmod_event_shims[] = {
    {"_FMOD_EventSystem_Create@4", fmod_EventSystem_Create_},
    {"_FMOD_Event_SetCallback@12", fmod_Event_SetCallback_},
    {"?init@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@HIPAXI@Z", fmod_EventSystem_init_},
    {"?release@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmod_EventSystem_release_},
    {"?unload@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmod_EventSystem_unload_},
    {"?update@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmod_EventSystem_update_},
    {"?setMediaPath@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBD@Z", fmod_EventSystem_setMediaPath_},
    {"?getSystemObject@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PAPAVSystem@2@@Z", fmod_EventSystem_getSystemObject_},
    {"?getMusicSystem@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PAPAVMusicSystem@2@@Z", fmod_EventSystem_getMusicSystem_},
    {"?load@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBDPAUFMOD_EVENT_LOADINFO@@PAPAVEventProject@2@@Z", fmod_EventSystem_load_},
    {"?getProject@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBDPAPAVEventProject@2@@Z", fmod_EventSystem_getProject_},
    {"?getNumProjects@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PAH@Z", fmod_EventSystem_getNumProjects_},
    {"?getCategory@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBDPAPAVEventCategory@2@@Z", fmod_EventSystem_getCategory_},
    {"?getEvent@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBDIPAPAVEvent@2@@Z", fmod_EventSystem_getEvent_},
    {"?getEventByGUID@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@PBUFMOD_GUID@@IPAPAVEvent@2@@Z", fmod_EventSystem_getEventByGUID_},
    {"?set3DNumListeners@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@H@Z", fmod_EventSystem_set3DNumListeners_},
    {"?set3DListenerAttributes@EventSystem@FMOD@@QAG?AW4FMOD_RESULT@@HPBUFMOD_VECTOR@@000@Z", fmod_EventSystem_set3DListenerAttributes_},
    {"?release@EventProjectI@FMOD@@UAG?AW4FMOD_RESULT@@XZ", fmod_EventProject_release_},
    {"?getInfo@EventProjectI@FMOD@@UAG?AW4FMOD_RESULT@@PAUFMOD_EVENT_PROJECTINFO@@@Z", fmod_EventProject_getInfo_},
    {"?getGroupByIndex@EventProjectI@FMOD@@UAG?AW4FMOD_RESULT@@H_NPAPAVEventGroup@2@@Z", fmod_EventProject_getGroupByIndex_},
    {"?getNumGroups@EventProjectI@FMOD@@UAG?AW4FMOD_RESULT@@PAH@Z", fmod_EventProject_getNumGroups_},
    {"?freeEventData@EventGroupI@FMOD@@UAG?AW4FMOD_RESULT@@PAVEvent@2@_N@Z", fmod_EventGroup_freeEventData_},
    {"?getGroupByIndex@EventGroupI@FMOD@@UAG?AW4FMOD_RESULT@@H_NPAPAVEventGroup@2@@Z", fmod_EventGroup_getGroupByIndex_},
    {"?getNumGroups@EventGroupI@FMOD@@UAG?AW4FMOD_RESULT@@PAH@Z", fmod_EventGroup_getNumGroups_},
    {"?getEventByIndex@EventGroupI@FMOD@@UAG?AW4FMOD_RESULT@@HIPAPAVEvent@2@@Z", fmod_EventGroup_getEventByIndex_},
    {"?getNumEvents@EventGroupI@FMOD@@UAG?AW4FMOD_RESULT@@PAH@Z", fmod_EventGroup_getNumEvents_},
    {"?setVolume@EventCategoryI@FMOD@@UAG?AW4FMOD_RESULT@@M@Z", fmod_EventCategory_setVolume_},
    {"?setPaused@EventCategoryI@FMOD@@UAG?AW4FMOD_RESULT@@_N@Z", fmod_EventCategory_setPaused_},
    {"?loadSoundData@MusicSystemI@FMOD@@UAG?AW4FMOD_RESULT@@W4FMOD_EVENT_RESOURCE@@I@Z", fmod_MusicSystem_loadSoundData_},
    {"?getInfo@Event@FMOD@@QAG?AW4FMOD_RESULT@@PAHPAPADPAUFMOD_EVENT_INFO@@@Z", fmod_Event_getInfo_},
    {"?start@Event@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmod_Event_start_},
    {"?stop@Event@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z", fmod_Event_stop_},
    {"?setPaused@Event@FMOD@@QAG?AW4FMOD_RESULT@@_N@Z", fmod_Event_setPaused_},
    {"?getParameter@Event@FMOD@@QAG?AW4FMOD_RESULT@@PBDPAPAVEventParameter@2@@Z", fmod_Event_getParameter_},
    {"?getParameterByIndex@Event@FMOD@@QAG?AW4FMOD_RESULT@@HPAPAVEventParameter@2@@Z", fmod_Event_getParameterByIndex_},
    {"?getPropertyByIndex@Event@FMOD@@QAG?AW4FMOD_RESULT@@HPAX_N@Z", fmod_Event_getPropertyByIndex_},
    {"?setPropertyByIndex@Event@FMOD@@QAG?AW4FMOD_RESULT@@HPAX_N@Z", fmod_Event_setPropertyByIndex_},
    {"?setCallback@Event@FMOD@@QAG?AW4FMOD_RESULT@@P6G?AW43@PAUFMOD_EVENT@@W4FMOD_EVENT_CALLBACKTYPE@@PAX22@Z2@Z", fmod_Event_setCallback_},
    {"?set3DAttributes@Event@FMOD@@QAG?AW4FMOD_RESULT@@PBUFMOD_VECTOR@@00@Z", fmod_Event_set3DAttributes_},
    {"?getState@Event@FMOD@@QAG?AW4FMOD_RESULT@@PAI@Z", fmod_Event_getState_},
    {"?getParentGroup@Event@FMOD@@QAG?AW4FMOD_RESULT@@PAPAVEventGroup@2@@Z", fmod_Event_getParentGroup_},
    {"?getInfo@EventParameter@FMOD@@QAG?AW4FMOD_RESULT@@PAHPAPAD@Z", fmod_EventParameter_getInfo_},
    {"?setValue@EventParameter@FMOD@@QAG?AW4FMOD_RESULT@@M@Z", fmod_EventParameter_setValue_},
    {"?keyOff@EventParameter@FMOD@@QAG?AW4FMOD_RESULT@@XZ", fmod_EventParameter_keyOff_},
};

static ShimFn lookup_fmod_table(const FmodShimEntry *table, size_t count, const char *name) {
    if (!name) return NULL;
    for (size_t i = 0; i < count; i++) {
        if (!strcmp(name, table[i].name))
            return table[i].fn;
    }
    return NULL;
}

ShimFn smr_find_fmodex_fast_shim(const char *name) {
    return lookup_fmod_table(fmodex_shims, sizeof(fmodex_shims) / sizeof(fmodex_shims[0]), name);
}

ShimFn smr_find_fmod_event_fast_shim(const char *name) {
    return lookup_fmod_table(fmod_event_shims, sizeof(fmod_event_shims) / sizeof(fmod_event_shims[0]), name);
}
