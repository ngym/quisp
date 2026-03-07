cplusplus  {{
    #include <backends/interfaces/IQubit.h>
    using quisp::backends::abstract::IQubit;
}}

class IQubit {
    @existingClass;
    @opaque;
};

namespace quisp::messages;

message FlyingQubit
{
    string message_type = "qubit";
    IQubit *qubitRef;
    bool isFirst @getter(isFirst) @setter(setFirst) = false;
    bool isLast @getter(isLast) @setter(setLast) = false;
}
