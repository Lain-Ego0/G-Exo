#pragma once

#include <filesystem>
#include <string>

namespace gexo::deploy_tcn_pd::detail {

std::string sha256_file(const std::filesystem::path& path);

}  // namespace gexo::deploy_tcn_pd::detail

