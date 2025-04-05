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