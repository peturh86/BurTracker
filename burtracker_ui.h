#pragma once
#include <M5Unified.h>
#include <string>

namespace burtracker {
struct Screen {
  int mode = 0;
  int request_mode = 0;
  bool spoil_armed = false;
  std::string title = "Starting scanner";
  std::string detail = "Please wait";
  std::string price;
  std::string footer = "BURTRACKER";
  uint32_t colors[3] = {0x62DE9C, 0xFF707C, 0xFFD166};

  const char* intent() const {
    return mode == 1 ? "spoiled" : mode == 2 ? "price" : "shopping";
  }

  void wrapped(const std::string& text, int y, int lines) {
    auto& d = M5.Display;
    std::string line;
    size_t pos = 0;
    for (int row = 0; row < lines && pos < text.size(); ++row) {
      line.clear();
      while (pos < text.size()) {
        unsigned char c = text[pos];
        size_t n = c < 0x80 ? 1 : c < 0xE0 ? 2 : c < 0xF0 ? 3 : 4;
        n = std::min(n, text.size() - pos);
        std::string next = line + text.substr(pos, n);
        if (d.textWidth(next.c_str()) > 268 && !line.empty()) break;
        line = next;
        pos += n;
      }
      if (row == lines - 1 && pos < text.size()) {
        while (!line.empty() && d.textWidth((line + "...").c_str()) > 268) {
          size_t start = line.size() - 1;
          while (start > 0 && (static_cast<unsigned char>(line[start]) & 0xC0) == 0x80) --start;
          line.erase(start);
        }
        line += "...";
      }
      d.drawString(line.c_str(), 26, y + row * 20);
    }
  }

  void render() {
    auto& d = M5.Display;
    constexpr uint32_t bg = 0x101923, panel = 0x1C2937, muted = 0x9AABBC;
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
    d.fillCircle(15, 59, 3, colors[mode]);
    d.setTextColor(muted);
    d.drawString(mode == 0 ? "KRONAN / HA LIST" :
                 mode == 1 ? "REPORT SPOILAGE" : "KRONAN PRICE CHECK", 26, 51);
    d.fillRoundRect(12, 76, 296, 125, 12, panel);
    d.fillRoundRect(12, 89, 3, 98, 1, colors[mode]);
    d.setTextColor(0xF3F7FA);
    wrapped(title, 88, price.empty() ? 3 : 2);
    if (!price.empty()) {
      d.setFont(&fonts::Font0);
      d.setTextSize(3);
      d.setTextColor(colors[mode]);
      d.drawString(price.c_str(), 26, 143);
      d.setFont(&fonts::efontJA_16);
      d.setTextSize(1);
    }
    d.setTextColor(muted);
    d.drawString(detail.c_str(), 26, 178);
    d.setFont(&fonts::Font0);
    d.setTextColor(0x9AABBC);
    d.drawCenterString(footer.c_str(), 160, 217);
    d.endWrite();
  }

  void select(int selected) {
    mode = selected;
    spoil_armed = mode == 1;
    price.clear();
    title = "Show a barcode";
    detail = mode == 0 ? "Add it to Kronan / HA" :
             mode == 1 ? "Record one spoiled item" : "Look up the catalog price";
    footer = mode == 1 ? "ONE SCAN ARMED" : "SCAN WHEN READY";
    render();
  }

  void waiting() {
    request_mode = mode;
    if (mode == 1) spoil_armed = false;
    title = "Reading product...";
    detail = "Waiting for Home Assistant";
    price.clear();
    footer = mode == 1 ? "ONE SPOILAGE REPORT" : "KRONAN LOOKUP";
    render();
  }

  void result(const std::string& status, const std::string& name,
              const std::string& price_text, const std::string& outcome) {
    price = price_text;
    title = name.empty() ? "Product unavailable" : name;
    detail = outcome == "reported" || outcome == "already_reported" ? "Spoilage recorded" :
             outcome == "lookup_only" ? "Catalog price / ISK" :
             outcome == "save_failed" ? "Nothing recorded" :
             outcome == "kronan_added" ? "On Kronan / HA list" :
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
              status == "list_failed" || status == "list_missing" ? "Kronan list unavailable" : "Lookup unavailable";
      if (status == "write_uncertain") detail = "Addition could not be confirmed";
    } else if (request_mode == 2 && price.empty()) {
      detail = "No catalog price available";
    }
    footer = mode == 1 ? "PRESS SPOILED TO SCAN NEXT" :
             mode == 2 ? "CATALOG PRICE / CACHE UP TO 5 MIN" : "READY FOR THE NEXT ITEM";
    render();
  }
};
static Screen screen;
}
