# HOme_AI
HOme智能家居系统flask相关代码

# 相关命令行指令
1. 登录到服务器
ssh ubuntu@43.155.36.236
后面输入密码即可：大写开头
2. 本地更新后的代码推到服务器
scp flask_face_server.py ubuntu@43.155.36.236:/home/ubuntu/face_detect/ 
3. 远端服务器查看进行的进程
sudo lsof -i :5000
4. 杀死进程
sudo kill -9 [pid]
5. 后台启动进程
nohup python3 flask_face_server.py > server.log 2>&1 &
6. 查看日志
tail -f server.log
7. 激活虚拟环境
source venv/bin/activate
8. 切换工作目录
cd ~/face_detect
9. 登录到数据库
mysql -u root -p
密码：123456
10. 查看数据库
USE home_database;
11. 删除数据表数据
DELETE FROM device_data;
12. 查看数据表数据
SELECT * FROM device_data;
13. 启动数据库服务
sudo systemctl start mysql
14. 建表语句
CREATE DATABASE IF NOT EXISTS home_database
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE home_database;

CREATE TABLE IF NOT EXISTS device_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    device_id VARCHAR(64) NOT NULL COMMENT '设备唯一标识',

    -- 控制/状态类
    led_lightness_color INT DEFAULT NULL COMMENT '灯光亮度或颜色值',
    curtain_percent INT DEFAULT NULL COMMENT '窗帘百分比',
    door_state INT DEFAULT NULL COMMENT '门锁状态',
    light INT DEFAULT NULL COMMENT '灯状态',
    beep_state INT DEFAULT NULL COMMENT '蜂鸣器状态',
    airConditioner_state INT DEFAULT NULL COMMENT '空调状态',
    automation_mode_scene INT UNSIGNED DEFAULT NULL COMMENT '自动化模式ID',

    -- 环境感知
    temperature_indoor FLOAT DEFAULT NULL COMMENT '室内温度',
    humidity_indoor FLOAT DEFAULT NULL COMMENT '室内湿度',
    smoke INT DEFAULT NULL COMMENT '烟雾浓度',
    comb INT DEFAULT NULL COMMENT '可燃气体浓度',
    sr501_state INT DEFAULT NULL COMMENT '人体移动状态',

    -- 能耗监测
    current INT UNSIGNED DEFAULT NULL COMMENT '电流(uA)',
    voltage INT UNSIGNED DEFAULT NULL COMMENT '电压(uV)',
    power INT UNSIGNED DEFAULT NULL COMMENT '功率(uW)',

    -- 时间戳
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '上报时间',

    -- 索引优化
    INDEX idx_device_created_at (device_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='设备上报数据表';
