#pragma once

#include <filesystem>
#include <string>

namespace gexo::deploy::detail {

std::string sha256_file(const std::filesystem::path& path);

}  // namespace gexo::deploy::detail
