#include <iostream>
#include <algorithm>
#include <vector>

using namespace std;

bool is_palindrome(const std::string& str) {
    return std::equal(str.begin(), str.begin() + str.size() / 2, str.rbegin());
}

class Solution {
private:
    vector<vector<string>> result;
    vector<string> path;

    void backtracking(const string& s, int start) {
        if (start == s.size()) {
            result.push_back(path);
            return;
        }

        for (int i = start; i < s.size(); i++) {
            string sub = s.substr(start, i - start + 1);
            if (is_palindrome(sub)) {
                path.push_back(sub);
                backtracking(s, i + 1);
                path.pop_back();
            }
        }
    }

public:
    vector<vector<string>> partition(string s) {
        result.clear();
        path.clear();
        backtracking(s, 0);
        return result;
    }
};

int main(){
    Solution sol;

    vector<string> test_cases = {"aab", "a", "aaa", "ab"};

    for (const auto& s : test_cases) {
        cout << "字符串 \"" << s << "\" 的回文分割方案：\n";
        vector<vector<string>> ans = sol.partition(s);
        for (const auto& scheme : ans) {
            cout << "  [";
            for (size_t i = 0; i < scheme.size(); i++) {
                cout << "\"" << scheme[i] << "\"";
                if (i < scheme.size() - 1) cout << ", ";
            }
            cout << "]\n";
        }
        cout << "共 " << ans.size() << " 种方案\n\n";
    }

    return 0;
}