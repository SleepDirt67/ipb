#pragma once

#include <algorithm>
#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace SpawnLuaSource
{
struct Token
{
    size_t offset;
    std::string_view text;
};

inline bool Space(char ch)
{
    return ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' || ch == '\f' || ch == '\v';
}

inline bool Digit(char ch) { return ch >= '0' && ch <= '9'; }
inline bool Name(char ch)
{
    return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
        ch == '_' || static_cast<unsigned char>(ch) >= 128;
}

inline size_t LongBracket(std::string_view input, size_t start, char bracket)
{
    if (start >= input.size() || input[start] != bracket)
        return 0;
    size_t next = start + 1;
    while (next < input.size() && input[next] == '=')
        ++next;
    return next < input.size() && input[next] == bracket ? next - start + 1 : 0;
}

inline bool Tokenize(std::string_view input, std::vector<Token>& out)
{
    size_t pos = 0;
    while (pos < input.size())
    {
        if (Space(input[pos]))
        {
            ++pos;
            continue;
        }

        const bool comment = input.substr(pos).starts_with("--");
        const auto first = pos;
        if (comment)
            pos += 2;
        const auto bracket = LongBracket(input, pos, '[');
        if (bracket)
        {
            pos += bracket;
            do
            {
                pos = input.find(']', pos);
                if (pos == std::string_view::npos)
                    return false;
                if (LongBracket(input, pos, ']') == bracket)
                    break;
                ++pos;
            } while (true);
            pos += bracket;
        }
        else if (comment)
        {
            pos = input.find_first_of("\r\n", pos);
            if (pos == std::string_view::npos)
                pos = input.size();
        }
        else if (input[pos] == '"' || input[pos] == '\'')
        {
            const char quote = input[pos++];
            bool closed = false;
            while (pos < input.size())
            {
                const char ch = input[pos++];
                if (ch == quote)
                {
                    closed = true;
                    break;
                }
                if (ch == '\\' && pos < input.size())
                {
                    if (input[pos] == '\r' && pos + 1 < input.size() && input[pos + 1] == '\n')
                        ++pos;
                    ++pos;
                }
            }
            if (!closed)
                return false;
        }
        else if (Digit(input[pos]) || (input[pos] == '.' && pos + 1 < input.size() && Digit(input[pos + 1])))
        {
            const bool hex = input.substr(pos).starts_with("0x") || input.substr(pos).starts_with("0X");
            ++pos;
            while (pos < input.size())
            {
                const char ch = input[pos], prev = input[pos - 1];
                if (!Digit(ch) && !Name(ch) && ch != '.' &&
                    !((ch == '+' || ch == '-') && (hex ? (prev == 'p' || prev == 'P') : (prev == 'e' || prev == 'E'))))
                    break;
                ++pos;
            }
        }
        else if (Name(input[pos]))
        {
            do { ++pos; } while (pos < input.size() && (Name(input[pos]) || Digit(input[pos])));
        }
        else
        {
            const auto tail = input.substr(pos);
            if (tail.starts_with("..."))
                pos += 3;
            else if (tail.starts_with("..") || tail.starts_with("==") || tail.starts_with("~=") ||
                     tail.starts_with(">=") || tail.starts_with("<=") || tail.starts_with("::"))
                pos += 2;
            else
                ++pos;
        }
        if (!comment)
            out.push_back({first, input.substr(first, pos - first)});
    }
    return true;
}

struct Range { size_t start, length; };

inline std::optional<Range> FindUnique(std::string_view source, std::string_view expected)
{
    std::vector<Token> tokens, pattern;
    if (!Tokenize(source, tokens) || !Tokenize(expected, pattern) || pattern.empty())
        return std::nullopt;
    const auto equal = [](const Token& a, const Token& b) { return a.text == b.text; };
    const auto first = std::search(tokens.begin(), tokens.end(), pattern.begin(), pattern.end(), equal);
    if (first == tokens.end() ||
        (first != tokens.begin() && (first - 1)->text == "local") ||
        std::search(first + 1, tokens.end(), pattern.begin(), pattern.end(), equal) != tokens.end())
        return std::nullopt;
    const auto& last = *(first + pattern.size() - 1);
    return Range{first->offset, last.offset + last.text.size() - first->offset};
}
}
