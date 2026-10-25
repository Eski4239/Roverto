// console.h — non-blocking USB serial line reader (fixed buffer, no String).
#pragma once

namespace console {

// Returns a complete, trimmed command line (without CR/LF) once one has arrived, else nullptr.
// The pointer stays valid until the next call.
const char* poll();

}  // namespace console
