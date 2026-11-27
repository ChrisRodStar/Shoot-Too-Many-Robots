#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include "host.h"

typedef enum { VC90, PHYSX, D3DX, FMOD } ModuleGroup;

typedef struct {
    const char *filename;
    uint32_t base;
    uint32_t size;
    uint32_t entry;
    uint32_t exports;
    uint32_t export_size;
    uint32_t text_start;
    uint32_t text_end;
    ModuleGroup group;
} RuntimeModule;

static RuntimeModule modules[] = {
    {.filename = "msvcr90.dll", .base = 0x78520000u},
    {.filename = "msvcp90.dll", .base = 0x78480000u},
    {.filename = "cudart32_30_9.dll", .base = 0x11000000u, .group = PHYSX},
    {.filename = "PhysXCore.dll", .base = 0x11400000u, .group = PHYSX},
    {.filename = "PhysXCooking.dll", .base = 0x11800000u, .group = PHYSX},
    {.filename = "PhysXDevice.dll", .base = 0x11900000u, .group = PHYSX},
    {.filename = "PhysXLoader.dll", .base = 0x10000000u, .group = PHYSX},
    {.filename = "d3dcompiler_43.dll", .base = 0x12000000u, .group = D3DX},
    {.filename = "d3dx9_43.dll", .base = 0x12400000u, .group = D3DX},
    {.filename = "fmodex.dll", .base = 0x13000000u, .group = FMOD},
    {.filename = "fmod_event.dll", .base = 0x13200000u, .group = FMOD},
};

extern void smr_bind_imports(uint32_t base);
extern int host_run_guest(CPU *cpu, uint32_t entry);
extern int gheap_reserve_fixed(uint32_t lo, uint32_t hi);

static uint16_t word_at(const uint8_t *source) {
    uint16_t result;
    memcpy(&result, source, sizeof(result));
    return result;
}

static uint32_t dword_at(const uint8_t *source) {
    uint32_t result;
    memcpy(&result, source, sizeof(result));
    return result;
}

static bool contains(size_t total, size_t start, size_t length) {
    return start <= total && length <= total - start;
}

static bool relocate_image(uint8_t *image, uint32_t image_size, uint32_t offset,
                           uint32_t length, uint32_t delta) {
    if (!delta)
        return true;
    if (!length || !contains(image_size, offset, length))
        return false;
    for (uint32_t cursor = 0; cursor < length;) {
        if (!contains(length, cursor, 8))
            return false;
        const uint8_t *block = image + offset + cursor;
        uint32_t page = dword_at(block);
        uint32_t size = dword_at(block + 4);
        if (size < 8 || (size & 1u) || !contains(length, cursor, size))
            return false;
        for (uint32_t entry = 8; entry < size; entry += 2) {
            uint16_t fixup = word_at(block + entry);
            uint16_t type = fixup >> 12;
            if (!type)
                continue;
            uint64_t address = (uint64_t)page + (fixup & 0xfffu);
            if (type != 3 || !contains(image_size, address, 4))
                return false;
            uint32_t relocated = dword_at(image + address) + delta;
            memcpy(image + address, &relocated, sizeof(relocated));
        }
        cursor += size;
    }
    return true;
}

static bool map_module(RuntimeModule *module, const char *directory) {
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/%s", directory, module->filename) >= (int)sizeof(path))
        return false;

    FILE *file = fopen(path, "rb");
    if (!file)
        return false;
    if (fseek(file, 0, SEEK_END) != 0) {
        fclose(file);
        return false;
    }
    long length = ftell(file);
    if (length < 64 || length > 0x1000000 || fseek(file, 0, SEEK_SET) != 0) {
        fclose(file);
        return false;
    }
    uint8_t *data = malloc((size_t)length);
    bool read_ok = data && fread(data, 1, (size_t)length, file) == (size_t)length;
    fclose(file);
    if (!read_ok) {
        free(data);
        return false;
    }

    uint32_t pe = dword_at(data + 0x3c);
    bool valid = false;
    if (word_at(data) != 0x5a4d || !contains(length, pe, 24 + 176)
        || dword_at(data + pe) != 0x4550 || word_at(data + pe + 4) != 0x14c)
        goto done;

    uint16_t sections = word_at(data + pe + 6);
    uint16_t optional_size = word_at(data + pe + 20);
    const uint8_t *optional = data + pe + 24;
    size_t section_table = (size_t)pe + 24 + optional_size;
    if (optional_size < 176 || word_at(optional) != 0x10b
        || !(word_at(data + pe + 22) & 0x2000)
        || !contains(length, section_table, (size_t)sections * 40)
        || dword_at(optional + 92) < 10 || dword_at(optional + 168) != 0)
        goto done;

    uint32_t image_size = dword_at(optional + 56);
    uint32_t headers = dword_at(optional + 60);
    uint32_t entry = dword_at(optional + 16);
    uint32_t exports = dword_at(optional + 96);
    uint32_t export_size = dword_at(optional + 100);
    if (image_size > 0x400000 || !contains(length, 0, headers)
        || !contains(image_size, 0, headers) || !contains(image_size, entry, 1)
        || export_size < 40 || !contains(image_size, exports, export_size)
        || !gheap_reserve_fixed(module->base, module->base + image_size))
        goto done;

    uint8_t *image = MEM + module->base;
    memcpy(image, data, headers);
    for (uint16_t index = 0; index < sections; index++) {
        const uint8_t *section = data + section_table + (size_t)index * 40;
        uint32_t virtual_size = dword_at(section + 8);
        uint32_t address = dword_at(section + 12);
        uint32_t raw_size = dword_at(section + 16);
        uint32_t raw_address = dword_at(section + 20);
        uint32_t copy_size = virtual_size && virtual_size < raw_size ? virtual_size : raw_size;
        if (!contains(image_size, address, copy_size) || !contains(length, raw_address, copy_size))
            goto done;
        memcpy(image + address, data + raw_address, copy_size);
        if (!memcmp(section, ".text", 5) && (dword_at(section + 36) & 0x20000000u)) {
            module->text_start = module->base + address;
            module->text_end = module->text_start + copy_size;
        }
    }

    if (!relocate_image(image, image_size, dword_at(optional + 136),
                        dword_at(optional + 140), module->base - dword_at(optional + 28)))
        goto done;

    module->size = image_size;
    module->entry = module->base + entry;
    module->exports = exports;
    module->export_size = export_size;
    valid = module->entry >= module->text_start && module->entry < module->text_end;
done:
    free(data);
    return valid;
}

bool smr_load_modules(const char *vc90_directory, const char *physx_directory,
                      const char *d3dx_directory) {
    const char *directories[] = {[VC90] = vc90_directory, [PHYSX] = physx_directory,
                                 [D3DX] = d3dx_directory, [FMOD] = physx_directory};
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++) {
        const char *directory = directories[modules[index].group];
        if (!directory)
            continue;
        if (!map_module(&modules[index], directory)) {
            fprintf(stderr, "[guest-dll] could not map %s\n", modules[index].filename);
            return false;
        }
        fprintf(stderr, "[guest-dll] mapped %s at %#x\n",
                modules[index].filename, modules[index].base);
    }

    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++)
        if (modules[index].size)
            smr_bind_imports(modules[index].base);
    return true;
}

uint32_t smr_module_export(const char *dll, const char *name) {
    if (name[0] == '#')
        return 0;
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++) {
        const RuntimeModule *module = &modules[index];
        if (!module->size || strcasecmp(dll, module->filename))
            continue;

        const uint8_t *image = MEM + module->base;
        const uint8_t *exports = image + module->exports;
        uint32_t functions = dword_at(exports + 20);
        uint32_t names = dword_at(exports + 24);
        uint32_t function_table = dword_at(exports + 28);
        uint32_t name_table = dword_at(exports + 32);
        uint32_t ordinal_table = dword_at(exports + 36);
        if (!contains(module->size, function_table, (size_t)functions * 4)
            || !contains(module->size, name_table, (size_t)names * 4)
            || !contains(module->size, ordinal_table, (size_t)names * 2))
            return 0;

        for (uint32_t slot = 0; slot < names; slot++) {
            uint32_t offset = dword_at(image + name_table + 4 * slot);
            if (!contains(module->size, offset, 1)
                || !memchr(image + offset, 0, module->size - offset)
                || strcmp(name, (const char *)image + offset))
                continue;

            uint16_t ordinal = word_at(image + ordinal_table + 2 * slot);
            if (ordinal >= functions)
                return 0;
            uint32_t address = dword_at(image + function_table + 4 * ordinal);
            if (!address || address >= module->size ||
                contains(module->export_size, (size_t)address - module->exports, 1))
                return 0;
            return module->base + address;
        }
    }
    return 0;
}

uint32_t smr_module_by_name(const char *name) {
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++) {
        const RuntimeModule *module = &modules[index];
        size_t length = strlen(module->filename) - 4;
        if (module->size && (!strcasecmp(name, module->filename)
            || (strlen(name) == length && !strncasecmp(name, module->filename, length))))
            return module->base;
    }
    return 0;
}

uint32_t smr_module_export_by_handle(uint32_t handle, const char *name) {
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++)
        if (modules[index].size && modules[index].base == handle)
            return smr_module_export(modules[index].filename, name);
    return 0;
}

bool smr_mapped_module_handle(uint32_t handle) {
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++)
        if (modules[index].size && modules[index].base == handle)
            return true;
    return false;
}

bool smr_module_executable_address(uint32_t address) {
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++)
        if (address >= modules[index].text_start && address < modules[index].text_end)
            return true;
    return false;
}

bool smr_module_uses_legacy_crt(uint32_t base) {
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++)
        if (modules[index].size && modules[index].base == base)
            return modules[index].group == D3DX || modules[index].group == FMOD;
    return false;
}

bool smr_attach_modules(CPU *cpu) {
    uint32_t stack = REG(cpu, R_ESP);
    for (size_t index = 0; index < sizeof(modules) / sizeof(modules[0]); index++) {
        const RuntimeModule *module = &modules[index];
        if (!module->size)
            continue;
        P32(stack - 16, HOST_EXIT_THUNK);
        P32(stack - 12, module->base);
        P32(stack - 8, 1); // DLL_PROCESS_ATTACH
        P32(stack - 4, 1); // Non-null for process startup.
        SETREG(cpu, R_ESP, stack - 16);
        fprintf(stderr, "[guest-dll] attaching %s at %#x\n", module->filename, module->entry);
        if (host_run_guest(cpu, module->entry) || !REG(cpu, R_EAX))
            return false;
        SETREG(cpu, R_ESP, stack);
        fprintf(stderr, "[guest-dll] attached %s\n", module->filename);
    }
    return true;
}
