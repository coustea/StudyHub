/*
 * LeetCode 53. Maximum Subarray
 * 题目：给定一个整数数组 nums，找到一个具有最大和的连续子数组（子数组最少包含一个元素），返回其最大和。
 *
 * 算法：Kadane's Algorithm（动态规划）
 * 时间复杂度：O(n)
 * 空间复杂度：O(1)
 */

#include <vector>
#include <algorithm>
#include <iostream>

using namespace std;

class Solution {
public:
    int maxSubArray(vector<int>& nums) {
        int max_sum = nums[0];      // 全局最大和
        int current_sum = nums[0];  // 以当前位置结尾的连续子数组的最大和

        for (int i = 1; i < nums.size(); i++) {
            // 状态转移：要么将当前元素加入之前的子数组，要么从当前元素重新开始
            current_sum = max(nums[i], current_sum + nums[i]);
            // 更新全局最大值
            max_sum = max(max_sum, current_sum);
        }

        return max_sum;
    }
};

// 测试代码
int main() {
    Solution solution;

    // 测试用例 1
    vector<int> nums1 = {-2, 1, -3, 4, -1, 2, 1, -5, 4};
    cout << "Test 1: " << solution.maxSubArray(nums1) << endl;  // 期望输出: 6

    // 测试用例 2
    vector<int> nums2 = {1};
    cout << "Test 2: " << solution.maxSubArray(nums2) << endl;  // 期望输出: 1

    // 测试用例 3
    vector<int> nums3 = {5, 4, -1, 7, 8};
    cout << "Test 3: " << solution.maxSubArray(nums3) << endl;  // 期望输出: 23

    return 0;
}
