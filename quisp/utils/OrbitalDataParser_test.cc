#include <gtest/gtest.h>

#include <test_utils/TestUtils.h>
#include <filesystem>

#include <fstream>

#include "OrbitalDataParser.h"

#include <cstdio>

using namespace quisp_test;
using namespace quisp_test::utils;
using namespace quisp::messages;
using namespace quisp::modules::SharedResource;

namespace {

class OrbitalDataParserTest : public ::testing::Test {
 protected:
  void SetUp() {
    csv_path = std::filesystem::temp_directory_path() / "quisp_test_orbital_data.csv";
    csv_to_generate.open(csv_path);
    csv_to_generate << "200,100000\n";
    csv_to_generate << "300,300000\n";
    csv_to_generate << "400,200000\n";
    csv_to_generate.close();
    csv_parser = new OrbitalDataParser(csv_path.string());
  }
  void TearDown() {
    delete csv_parser;
    std::remove(csv_path.string().c_str());
  }

  std::filesystem::path csv_path;
  OrbitalDataParser* csv_parser = nullptr;
  std::ofstream csv_to_generate;
};

TEST_F(OrbitalDataParserTest, lowerBound) {
  ASSERT_DOUBLE_EQ(csv_parser->getLowestDatapoint(), 200);
  ASSERT_DOUBLE_EQ(csv_parser->getLowestDatavalue(), 100000);
}

TEST_F(OrbitalDataParserTest, upperBound) {
  ASSERT_DOUBLE_EQ(csv_parser->getHighestDatapoint(), 400);
  ASSERT_DOUBLE_EQ(csv_parser->getHighestDatavalue(), 200000);
}

TEST_F(OrbitalDataParserTest, lowerThanLB) { ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(100), 100000); }

TEST_F(OrbitalDataParserTest, higherThanUB) { ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(500), 200000); }

TEST_F(OrbitalDataParserTest, normalOperation) {
  ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(250), 200000);
  ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(300), 300000);
  ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(350), 250000);
  ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(234.5), 169000);
  ASSERT_DOUBLE_EQ(csv_parser->getPropertyAtTime(287.4), 274800);
}

}  // namespace
