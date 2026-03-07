//
// Generated file, do not edit! Created by opp_msgtool 6.3 from FlyingQubit.msg.
//

// Disable warnings about unused variables, empty switch stmts, etc:
#ifdef _MSC_VER
#  pragma warning(disable:4101)
#  pragma warning(disable:4065)
#endif

#if defined(__clang__)
#  pragma clang diagnostic ignored "-Wshadow"
#  pragma clang diagnostic ignored "-Wconversion"
#  pragma clang diagnostic ignored "-Wunused-parameter"
#  pragma clang diagnostic ignored "-Wc++98-compat"
#  pragma clang diagnostic ignored "-Wunreachable-code-break"
#  pragma clang diagnostic ignored "-Wold-style-cast"
#elif defined(__GNUC__)
#  pragma GCC diagnostic ignored "-Wshadow"
#  pragma GCC diagnostic ignored "-Wconversion"
#  pragma GCC diagnostic ignored "-Wunused-parameter"
#  pragma GCC diagnostic ignored "-Wold-style-cast"
#  pragma GCC diagnostic ignored "-Wsuggest-attribute=noreturn"
#  pragma GCC diagnostic ignored "-Wfloat-conversion"
#endif

#include <iostream>
#include <sstream>
#include <memory>
#include <type_traits>
#include "FlyingQubit_m.h"

namespace omnetpp {

// Template pack/unpack rules. They are declared *after* a1l type-specific pack functions for multiple reasons.
// They are in the omnetpp namespace, to allow them to be found by argument-dependent lookup via the cCommBuffer argument

// Packing/unpacking an std::vector
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::vector<T,A>& v)
{
    int n = v.size();
    doParsimPacking(buffer, n);
    for (int i = 0; i < n; i++)
        doParsimPacking(buffer, v[i]);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::vector<T,A>& v)
{
    int n;
    doParsimUnpacking(buffer, n);
    v.resize(n);
    for (int i = 0; i < n; i++)
        doParsimUnpacking(buffer, v[i]);
}

// Packing/unpacking an std::list
template<typename T, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::list<T,A>& l)
{
    doParsimPacking(buffer, (int)l.size());
    for (typename std::list<T,A>::const_iterator it = l.begin(); it != l.end(); ++it)
        doParsimPacking(buffer, (T&)*it);
}

template<typename T, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::list<T,A>& l)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        l.push_back(T());
        doParsimUnpacking(buffer, l.back());
    }
}

// Packing/unpacking an std::set
template<typename T, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::set<T,Tr,A>& s)
{
    doParsimPacking(buffer, (int)s.size());
    for (typename std::set<T,Tr,A>::const_iterator it = s.begin(); it != s.end(); ++it)
        doParsimPacking(buffer, *it);
}

template<typename T, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::set<T,Tr,A>& s)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        T x;
        doParsimUnpacking(buffer, x);
        s.insert(x);
    }
}

// Packing/unpacking an std::map
template<typename K, typename V, typename Tr, typename A>
void doParsimPacking(omnetpp::cCommBuffer *buffer, const std::map<K,V,Tr,A>& m)
{
    doParsimPacking(buffer, (int)m.size());
    for (typename std::map<K,V,Tr,A>::const_iterator it = m.begin(); it != m.end(); ++it) {
        doParsimPacking(buffer, it->first);
        doParsimPacking(buffer, it->second);
    }
}

template<typename K, typename V, typename Tr, typename A>
void doParsimUnpacking(omnetpp::cCommBuffer *buffer, std::map<K,V,Tr,A>& m)
{
    int n;
    doParsimUnpacking(buffer, n);
    for (int i = 0; i < n; i++) {
        K k; V v;
        doParsimUnpacking(buffer, k);
        doParsimUnpacking(buffer, v);
        m[k] = v;
    }
}

// Default pack/unpack function for arrays
template<typename T>
void doParsimArrayPacking(omnetpp::cCommBuffer *b, const T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimPacking(b, t[i]);
}

template<typename T>
void doParsimArrayUnpacking(omnetpp::cCommBuffer *b, T *t, int n)
{
    for (int i = 0; i < n; i++)
        doParsimUnpacking(b, t[i]);
}

// Default rule to prevent compiler from choosing base class' doParsimPacking() function
template<typename T>
void doParsimPacking(omnetpp::cCommBuffer *, const T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimPacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

template<typename T>
void doParsimUnpacking(omnetpp::cCommBuffer *, T& t)
{
    throw omnetpp::cRuntimeError("Parsim error: No doParsimUnpacking() function for type %s", omnetpp::opp_typename(typeid(t)));
}

}  // namespace omnetpp

namespace quisp {
namespace messages {

Register_Class(FlyingQubit)

FlyingQubit::FlyingQubit(const char *name, short kind) : ::omnetpp::cMessage(name, kind)
{
}

FlyingQubit::FlyingQubit(const FlyingQubit& other) : ::omnetpp::cMessage(other)
{
    copy(other);
}

FlyingQubit::~FlyingQubit()
{
}

FlyingQubit& FlyingQubit::operator=(const FlyingQubit& other)
{
    if (this == &other) return *this;
    ::omnetpp::cMessage::operator=(other);
    copy(other);
    return *this;
}

void FlyingQubit::copy(const FlyingQubit& other)
{
    this->message_type = other.message_type;
    this->qubitRef = other.qubitRef;
    this->isFirst_ = other.isFirst_;
    this->isLast_ = other.isLast_;
}

void FlyingQubit::parsimPack(omnetpp::cCommBuffer *b) const
{
    ::omnetpp::cMessage::parsimPack(b);
    doParsimPacking(b,this->message_type);
    doParsimPacking(b,this->qubitRef);
    doParsimPacking(b,this->isFirst_);
    doParsimPacking(b,this->isLast_);
}

void FlyingQubit::parsimUnpack(omnetpp::cCommBuffer *b)
{
    ::omnetpp::cMessage::parsimUnpack(b);
    doParsimUnpacking(b,this->message_type);
    doParsimUnpacking(b,this->qubitRef);
    doParsimUnpacking(b,this->isFirst_);
    doParsimUnpacking(b,this->isLast_);
}

const char * FlyingQubit::getMessage_type() const
{
    return this->message_type.c_str();
}

void FlyingQubit::setMessage_type(const char * message_type)
{
    this->message_type = message_type;
}

const ::IQubit * FlyingQubit::getQubitRef() const
{
    return this->qubitRef;
}

void FlyingQubit::setQubitRef(::IQubit * qubitRef)
{
    this->qubitRef = qubitRef;
}

bool FlyingQubit::isFirst() const
{
    return this->isFirst_;
}

void FlyingQubit::setFirst(bool isFirst)
{
    this->isFirst_ = isFirst;
}

bool FlyingQubit::isLast() const
{
    return this->isLast_;
}

void FlyingQubit::setLast(bool isLast)
{
    this->isLast_ = isLast;
}

class FlyingQubitDescriptor : public omnetpp::cClassDescriptor
{
  private:
    mutable const char **propertyNames;
    enum FieldConstants {
        FIELD_message_type,
        FIELD_qubitRef,
        FIELD_isFirst,
        FIELD_isLast,
    };
  public:
    FlyingQubitDescriptor();
    virtual ~FlyingQubitDescriptor();

    virtual bool doesSupport(omnetpp::cObject *obj) const override;
    virtual const char **getPropertyNames() const override;
    virtual const char *getProperty(const char *propertyName) const override;
    virtual int getFieldCount() const override;
    virtual const char *getFieldName(int field) const override;
    virtual int findField(const char *fieldName) const override;
    virtual unsigned int getFieldTypeFlags(int field) const override;
    virtual const char *getFieldTypeString(int field) const override;
    virtual const char **getFieldPropertyNames(int field) const override;
    virtual const char *getFieldProperty(int field, const char *propertyName) const override;
    virtual int getFieldArraySize(omnetpp::any_ptr object, int field) const override;
    virtual void setFieldArraySize(omnetpp::any_ptr object, int field, int size) const override;

    virtual const char *getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const override;
    virtual std::string getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const override;
    virtual omnetpp::cValue getFieldValue(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const override;

    virtual const char *getFieldStructName(int field) const override;
    virtual omnetpp::any_ptr getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const override;
    virtual void setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const override;
};

Register_ClassDescriptor(FlyingQubitDescriptor)

FlyingQubitDescriptor::FlyingQubitDescriptor() : omnetpp::cClassDescriptor(omnetpp::opp_typename(typeid(quisp::messages::FlyingQubit)), "omnetpp::cMessage")
{
    propertyNames = nullptr;
}

FlyingQubitDescriptor::~FlyingQubitDescriptor()
{
    delete[] propertyNames;
}

bool FlyingQubitDescriptor::doesSupport(omnetpp::cObject *obj) const
{
    return dynamic_cast<FlyingQubit *>(obj)!=nullptr;
}

const char **FlyingQubitDescriptor::getPropertyNames() const
{
    if (!propertyNames) {
        static const char *names[] = {  nullptr };
        omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
        const char **baseNames = base ? base->getPropertyNames() : nullptr;
        propertyNames = mergeLists(baseNames, names);
    }
    return propertyNames;
}

const char *FlyingQubitDescriptor::getProperty(const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? base->getProperty(propertyName) : nullptr;
}

int FlyingQubitDescriptor::getFieldCount() const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    return base ? 4+base->getFieldCount() : 4;
}

unsigned int FlyingQubitDescriptor::getFieldTypeFlags(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeFlags(field);
        field -= base->getFieldCount();
    }
    static unsigned int fieldTypeFlags[] = {
        FD_ISEDITABLE,    // FIELD_message_type
        FD_ISPOINTER | FD_ISREPLACEABLE,    // FIELD_qubitRef
        FD_ISEDITABLE,    // FIELD_isFirst
        FD_ISEDITABLE,    // FIELD_isLast
    };
    return (field >= 0 && field < 4) ? fieldTypeFlags[field] : 0;
}

const char *FlyingQubitDescriptor::getFieldName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldName(field);
        field -= base->getFieldCount();
    }
    static const char *fieldNames[] = {
        "message_type",
        "qubitRef",
        "isFirst",
        "isLast",
    };
    return (field >= 0 && field < 4) ? fieldNames[field] : nullptr;
}

int FlyingQubitDescriptor::findField(const char *fieldName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    int baseIndex = base ? base->getFieldCount() : 0;
    if (strcmp(fieldName, "message_type") == 0) return baseIndex + 0;
    if (strcmp(fieldName, "qubitRef") == 0) return baseIndex + 1;
    if (strcmp(fieldName, "isFirst") == 0) return baseIndex + 2;
    if (strcmp(fieldName, "isLast") == 0) return baseIndex + 3;
    return base ? base->findField(fieldName) : -1;
}

const char *FlyingQubitDescriptor::getFieldTypeString(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldTypeString(field);
        field -= base->getFieldCount();
    }
    static const char *fieldTypeStrings[] = {
        "string",    // FIELD_message_type
        "IQubit",    // FIELD_qubitRef
        "bool",    // FIELD_isFirst
        "bool",    // FIELD_isLast
    };
    return (field >= 0 && field < 4) ? fieldTypeStrings[field] : nullptr;
}

const char **FlyingQubitDescriptor::getFieldPropertyNames(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldPropertyNames(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_isFirst: {
            static const char *names[] = { "getter", "setter",  nullptr };
            return names;
        }
        case FIELD_isLast: {
            static const char *names[] = { "getter", "setter",  nullptr };
            return names;
        }
        default: return nullptr;
    }
}

const char *FlyingQubitDescriptor::getFieldProperty(int field, const char *propertyName) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldProperty(field, propertyName);
        field -= base->getFieldCount();
    }
    switch (field) {
        case FIELD_isFirst:
            if (!strcmp(propertyName, "getter")) return "isFirst";
            if (!strcmp(propertyName, "setter")) return "setFirst";
            return nullptr;
        case FIELD_isLast:
            if (!strcmp(propertyName, "getter")) return "isLast";
            if (!strcmp(propertyName, "setter")) return "setLast";
            return nullptr;
        default: return nullptr;
    }
}

int FlyingQubitDescriptor::getFieldArraySize(omnetpp::any_ptr object, int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldArraySize(object, field);
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        default: return 0;
    }
}

void FlyingQubitDescriptor::setFieldArraySize(omnetpp::any_ptr object, int field, int size) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldArraySize(object, field, size);
            return;
        }
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        default: throw omnetpp::cRuntimeError("Cannot set array size of field %d of class 'FlyingQubit'", field);
    }
}

const char *FlyingQubitDescriptor::getFieldDynamicTypeString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldDynamicTypeString(object,field,i);
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_qubitRef: { const ::IQubit * value = pp->getQubitRef(); return omnetpp::opp_typename(typeid(*value)); }
        default: return nullptr;
    }
}

std::string FlyingQubitDescriptor::getFieldValueAsString(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValueAsString(object,field,i);
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_message_type: return oppstring2string(pp->getMessage_type());
        case FIELD_qubitRef: return "";
        case FIELD_isFirst: return bool2string(pp->isFirst());
        case FIELD_isLast: return bool2string(pp->isLast());
        default: return "";
    }
}

void FlyingQubitDescriptor::setFieldValueAsString(omnetpp::any_ptr object, int field, int i, const char *value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValueAsString(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_message_type: pp->setMessage_type((value)); break;
        case FIELD_isFirst: pp->setFirst(string2bool(value)); break;
        case FIELD_isLast: pp->setLast(string2bool(value)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'FlyingQubit'", field);
    }
}

omnetpp::cValue FlyingQubitDescriptor::getFieldValue(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldValue(object,field,i);
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_message_type: return pp->getMessage_type();
        case FIELD_qubitRef: return omnetpp::toAnyPtr(pp->getQubitRef()); break;
        case FIELD_isFirst: return pp->isFirst();
        case FIELD_isLast: return pp->isLast();
        default: throw omnetpp::cRuntimeError("Cannot return field %d of class 'FlyingQubit' as cValue -- field index out of range?", field);
    }
}

void FlyingQubitDescriptor::setFieldValue(omnetpp::any_ptr object, int field, int i, const omnetpp::cValue& value) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldValue(object, field, i, value);
            return;
        }
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_message_type: pp->setMessage_type(value.stringValue()); break;
        case FIELD_qubitRef: pp->setQubitRef(omnetpp::fromAnyPtr<::IQubit>(value.pointerValue())); break;
        case FIELD_isFirst: pp->setFirst(value.boolValue()); break;
        case FIELD_isLast: pp->setLast(value.boolValue()); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'FlyingQubit'", field);
    }
}

const char *FlyingQubitDescriptor::getFieldStructName(int field) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructName(field);
        field -= base->getFieldCount();
    }
    switch (field) {
        default: return nullptr;
    };
}

omnetpp::any_ptr FlyingQubitDescriptor::getFieldStructValuePointer(omnetpp::any_ptr object, int field, int i) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount())
            return base->getFieldStructValuePointer(object, field, i);
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_qubitRef: return omnetpp::toAnyPtr(pp->getQubitRef()); break;
        default: return omnetpp::any_ptr(nullptr);
    }
}

void FlyingQubitDescriptor::setFieldStructValuePointer(omnetpp::any_ptr object, int field, int i, omnetpp::any_ptr ptr) const
{
    omnetpp::cClassDescriptor *base = getBaseClassDescriptor();
    if (base) {
        if (field < base->getFieldCount()){
            base->setFieldStructValuePointer(object, field, i, ptr);
            return;
        }
        field -= base->getFieldCount();
    }
    FlyingQubit *pp = omnetpp::fromAnyPtr<FlyingQubit>(object); (void)pp;
    switch (field) {
        case FIELD_qubitRef: pp->setQubitRef(omnetpp::fromAnyPtr<::IQubit>(ptr)); break;
        default: throw omnetpp::cRuntimeError("Cannot set field %d of class 'FlyingQubit'", field);
    }
}

}  // namespace messages
}  // namespace quisp

namespace omnetpp {

}  // namespace omnetpp

