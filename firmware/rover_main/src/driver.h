// driver.h — common interface of every hardware item (docs/01 §5.1).
// Missing hardware = a driver with present=false that leaves its TELEM fields NaN.
#pragma once
#include <math.h>  // NAN
#include "rover_protocol.h"

struct Driver {
  const char* name;
  bool present = false;  // set by begin()

  explicit Driver(const char* n) : name(n) {}
  virtual ~Driver() = default;

  virtual bool begin() = 0;               // false if the hardware is not detected
  virtual void update() {}                // called every loop pass; keeps its own timing
  virtual void fill(TelemMsg& t) = 0;     // write its fields, or NaN if !present
  virtual void fillHello(HelloMsg&) {}    // set its hw_present bit / model if present
};
