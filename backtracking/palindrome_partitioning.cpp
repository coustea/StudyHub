/*
 * LeetCode 131. Palindrome Partitioning
 * 题目：给你一个字符串 s，请你将 s 分割成一些子串，使每个子串都是回文串。返回 s 所有可能的分割方案。
 *
 * 算法：Backtracking（回溯算法）
 * 时间复杂度：O(n * 2^n)
 * 空间复杂度：O(n)
 */

#include <string>
#include <vector>

using namespace std;

class Solution {
private:
    vector<vector<string>> result;
    vector<string> path;

    bool isPalindrome(const string& s, int left, int right) {
        while (left < right) {
            if (s[left] != s[right]) return false;
            left++;
            right--;
        }
        return true;
    }

    void backtracking(const string& s, int start) {
        if (start == s.size()) {
            result.push_back(path);
            return;
        }

        for (int i = start; i < s.size(); i++) {
            if (isPalindrome(s, start, i)) {
                path.push_back(s.substr(start, i - start + 1));
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