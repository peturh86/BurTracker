#pragma once
#include <M5Unified.h>
#include <string>
#include <vector>

namespace burtracker {
struct Screen {
  int mode = 0;
  int request_mode = 0;
  bool spoil_armed = false;
  std::string title = "Starting scanner";
  std::string detail;
  std::string price;
  uint32_t colors[3] = {0x62DE9C, 0xFF707C, 0xFFD166};

  const char* intent() const {
    return mode == 1 ? "spoiled" : mode == 2 ? "price" : "shopping";
  }

  std::vector<std::string> lines(const std::string& text) {
    std::vector<std::string> out;
    std::string line;
    for (size_t pos = 0; pos < text.size();) {
      unsigned char c = text[pos];
      size_t n = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
      n = std::min(n, text.size() - pos);
      std::string next = line + text.substr(pos, n);
      if (M5.Display.textWidth(next.c_str()) > 264 && !line.empty()) {
        size_t space = line.find_last_of(' ');
        if (space != std::string::npos && space > line.size() / 2) {
          out.push_back(line.substr(0, space));
          line = line.substr(space + 1);
        } else { out.push_back(line); line.clear(); }
      } else { line = next; pos += n; }
    }
    if (!line.empty()) out.push_back(line);
    return out;
  }

  void render() {
    auto& d = M5.Display;
    constexpr uint32_t bg = 0x101923, panel = 0x1C2937, muted = 0xAFC0D0;
    d.startWrite();
    d.fillScreen(bg);
    d.setTextDatum(top_left);
    d.setTextSize(1);
    d.setFont(&fonts::efontJA_16);
    const char* labels[3] = {"SHOP", "SPOILED", "PRICE"};
    for (int i = 0; i < 3; ++i) {
      int x = 8 + i * 104;
      d.fillRoundRect(x, 6, 96, 38, 8, i == mode ? colors[i] : panel);
      d.fillRoundRect(x + 10, 40, 76, 3, 1, colors[i]);
      d.setTextColor(i == mode ? bg : colors[i]);
      d.drawCenterString(labels[i], x + 48, 16);
      if (i == mode) d.fillTriangle(x + 42, 6, x + 54, 6, x + 48, 0, colors[i]);
    }
    d.fillRoundRect(8, 54, 304, 178, 12, panel);
    d.fillRoundRect(8, 69, 3, 148, 1, colors[mode]);
    d.setTextColor(0xF3F7FA);
    int available = price.empty() ? (detail.empty() ? 142 : 124) : 86;
    std::vector<std::string> wrapped;
    int line_height = 20;
    for (float scale : {2.0f, 1.5f, 1.0f}) {
      d.setTextSize(scale);
      line_height = int(16 * scale) + 4;
      wrapped = lines(title);
      if (int(wrapped.size()) * line_height <= available) break;
    }
    int limit = available / line_height;
    for (int i = 0; i < std::min(int(wrapped.size()), limit); ++i) {
      std::string line = wrapped[i];
      if (i == limit - 1 && int(wrapped.size()) > limit) {
        while (!line.empty() && d.textWidth((line + "...").c_str()) > 264) {
          size_t start = line.size() - 1;
          while (start && (static_cast<unsigned char>(line[start]) & 0xC0) == 0x80) --start;
          line.erase(start);
        }
        line += "...";
      }
      d.drawString(line.c_str(), 24, 68 + i * line_height);
    }
    if (!price.empty()) {
      d.setTextSize(2);
      if (d.textWidth(price.c_str()) > 264) d.setTextSize(1);
      d.setTextColor(colors[mode]);
      d.drawString(price.c_str(), 24, 161);
    }
    if (!detail.empty()) {
      d.setTextSize(1);
      d.setTextColor(muted);
      d.drawString(detail.c_str(), 24, 207);
    }
    d.setTextSize(1);
    d.endWrite();
  }

  void select(int selected) {
    mode = selected;
    spoil_armed = mode == 1;
    price.clear();
    title = "Show a barcode";
    detail.clear();
    render();
  }

  void waiting() {
    request_mode = mode;
    if (mode == 1) spoil_armed = false;
    title = "Reading product...";
    detail.clear();
    price.clear();
    render();
  }

  void result(const std::string& status, const std::string& name,
              const std::string& price_text, const std::string& outcome,
              const std::string& quantity = "") {
    price = price_text;
    title = name.empty() ? "Product unavailable" : name;
    detail = outcome == "reported" || outcome == "already_reported" ? "Spoilage recorded" :
             outcome == "lookup_only" ? "" :
             outcome == "save_failed" ? "Nothing recorded" :
             outcome == "kronan_added" ? (quantity.empty() ? "+1 added to HA" : "+1 added / " + quantity) :
             outcome == "unresolved" ? "Saved for identification" :
             outcome == "not_added" ? "Not added to Kronan" : "Shopping list updated";
    if (status != "resolved") {
      price.clear();
      title = status == "not_found" ? "Product not found" :
              status == "auth_required" ? "Set Kronan token in HA" :
              status == "rate_limited" ? "Please try again shortly" :
              status == "save_failed" ? "Could not save report" :
              status == "item_removed" ? "Item removed" :
              status == "write_uncertain" ? "Check your Kronan list" :
              status == "list_ambiguous" ? "Multiple HA lists found" :
              status == "quantity_limit" ? "Quantity limit reached" :
              status == "list_failed" || status == "list_missing" ? "Kronan list unavailable" : "Lookup unavailable";
      if (status == "write_uncertain") detail = "Addition could not be confirmed";
    } else if (request_mode == 2 && price.empty()) {
      detail = "No catalog price available";
    }
    if (mode == 1 && !spoil_armed && status == "resolved") detail = "Recorded / tap SPOILED for next";
    render();
  }
};
static Screen screen;
}
