#pragma once
#include "GraphState/Backend.h"
#include "interfaces/IConfiguration.h"
#include "interfaces/IGraphStateBackend.h"
#include "interfaces/IQubit.h"
#include "interfaces/IQubitId.h"
#include "modules/Backend/QubitConfiguration.h"

// the namespace for exposing the backend
namespace quisp::backends {

using abstract::EigenvalueResult;
using abstract::IConfiguration;
using abstract::IGraphStateBackend;
using abstract::IQubit;
using abstract::IQubitId;
using abstract::MeasurementOutcome;
using abstract::MeasureXResult;
using abstract::MeasureYResult;
using abstract::MeasureZResult;
using backends::StationaryQubitConfiguration;
using graph_state::GraphStateBackend;
using graph_state::GraphStateQubit;

}  // namespace quisp::backends
