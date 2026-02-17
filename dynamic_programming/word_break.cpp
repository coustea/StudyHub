/**
 * LeetCode 139 - 单词拆分
 *
 * 给定一个字符串 s 和一个字符串列表 wordDict 作为字典。
 * 判断是否可以利用字典中出现的一个或多个单词拼接出 s。
 *
 * 算法：记忆化搜索（递归 + 缓存）
 * 时间复杂度：O(n × m × k)，n = s.length(), m = wordDict.size(), k = 平均单词长度
 * 空间复杂度：O(n)
 */

#include <vector>
#include <string>
using namespace std;

class Solution {
public:
    vector<int> memo;  // memo[i]: -1未计算, 0失败, 1成功

    bool wordBreak(string s, vector<string>& wordDict) {
        memo.resize(s.size(), -1);
        return dfs(s, 0, wordDict);
    }

    bool dfs(string s, int pos, vector<string>& wordDict) {
        // 成功匹配完整个字符串
        if (pos == s.size()) {
            return true;
        }

        // 已经计算过，直接返回结果
        if (memo[pos] != -1) {
            return memo[pos] == 1;
        }

        // 尝试每个单词
        for (auto word : wordDict) {
            if (pos + word.size() <= s.size() && s.substr(pos, word.size()) == word) {
                if (dfs(s, pos + word.size(), wordDict)) {
                    memo[pos] = 1;  // 记录成功
                    return true;
                }
            }
        }

        memo[pos] = 0;  // 记录失败
        return false;
    }
};
