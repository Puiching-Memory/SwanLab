"""
@author: cunyue
@file: __init__.py
@time: 2025/6/16 13:29
@description: swanlab 客户端，负责发送 http 请求
"""

import json
from datetime import datetime
from typing import Optional, Tuple, Dict, Union, List, AnyStr

import requests
from requests.adapters import HTTPAdapter
from rich.status import Status
from urllib3.util.retry import Retry

from swanlab.error import NetworkError, ApiError
from swanlab.log import swanlog
from swanlab.package import get_package_version
from swanlab.toolkit import MediaBuffer
from .cos import CosClient
from .model import ProjectInfo, ExperimentInfo
from .. import auth


def decode_response(resp: requests.Response) -> Union[Dict, AnyStr, List]:
    """
    解码响应，返回信息
    低版本requests库没有JSONDecodeError，所以需要捕获两种异常
    """
    try:
        return resp.json()
    except json.decoder.JSONDecodeError:
        return resp.text
    except requests.JSONDecodeError:
        return resp.text


class Client:
    """
    封装请求函数，添加get、post、put、delete方法
    """

    REFRESH_TIME = 60 * 60 * 24 * 7  # 7天
    """
    刷新时间，单位秒，如果sid过期时间减去当前时间小于这个时间，就刷新sid
    """

    def __init__(self, login_info: auth.LoginInfo):
        """
        初始化会话
        """
        self.__login_info = login_info
        # 当前cos信息
        self.__cos: Optional[CosClient] = None
        # 当前项目信息
        self.__proj: Optional[ProjectInfo] = None
        # 当前实验信息
        self.__exp: Optional[ExperimentInfo] = None
        # 当前进程会话
        self.__session: Optional[requests.Session] = None
        # 当前项目所属的username
        self.__groupname = login_info.username
        self.__version = get_package_version()
        # 创建会话
        self.__create_session()

    # ---------------------------------- 一些辅助属性 ----------------------------------

    @property
    def base_url(self):
        return self.__login_info.api_host

    @property
    def api_host(self):
        return self.__login_info.web_host

    @property
    def api_key(self):
        return self.__login_info.api_key

    @property
    def web_host(self):
        return self.__login_info.web_host

    @property
    def groupname(self):
        """
        当前项目所属组名
        """
        return self.__groupname

    @property
    def username(self):
        """
        当前登录的用户名
        """
        return self.__login_info.username

    @property
    def cos(self):
        return self.__cos

    @property
    def proj_id(self):
        return self.__proj.cuid

    @property
    def projname(self):
        return self.__proj.name

    @property
    def history_exp_count(self):
        return self.__proj.history_exp_count

    @property
    def exp_id(self):
        return self.__exp.cuid

    @property
    def expname(self):
        return self.__exp.name

    @property
    def sid_expired_at(self):
        """
        获取sid的过期时间，字符串格式转时间
        """
        return datetime.strptime(self.__login_info.expired_at, "%Y-%m-%dT%H:%M:%S.%fZ")

    @property
    def web_proj_url(self):
        return f"{self.web_host}/@{self.groupname}/{self.projname}"

    @property
    def web_exp_url(self):
        return f"{self.web_proj_url}/runs/{self.exp_id}"

    # ---------------------------------- http方法 ----------------------------------

    def __before_request(self):
        """
        请求前的钩子
        """
        # FIXME datetime.utcnow() -> datetime.now(datetime.UTC)
        if (self.sid_expired_at - datetime.utcnow()).total_seconds() <= self.REFRESH_TIME:
            # 刷新sid，新建一个会话
            swanlog.debug("Refresh sid...")
            self.__login_info = auth.login_by_key(self.__login_info.api_key, save=False)
            self.__session.headers["cookie"] = f"sid={self.__login_info.sid}"

    def __create_session(self):
        """
        创建会话，这将在HTTP类实例化时调用
        添加了重试策略
        """
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["GET", "POST", "PUT", "DELETE", "PATCH"]),
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)

        session.headers["swanlab-sdk"] = self.__version
        session.cookies.update({"sid": self.__login_info.sid})

        # 注册响应钩子
        def response_interceptor(response: requests.Response, *args, **kwargs):
            """
            捕获所有的http不为2xx的错误，以ApiError的形式抛出
            """
            if response.status_code // 100 != 2:
                traceid = f"Trace id: {response.headers.get('traceid')}"
                request = f"{response.request.method.upper()} {response.url}"
                resp = f"{response.status_code} {response.reason}"
                raise ApiError(response, traceid, request, resp)

        session.hooks["response"] = response_interceptor

        self.__session = session

    def post(self, url: str, data: Union[dict, list] = None):
        """
        post请求
        """
        url = self.base_url + url
        self.__before_request()
        resp = self.__session.post(url, json=data)
        return decode_response(resp)

    def put(self, url: str, data: dict = None):
        """
        put请求
        """
        url = self.base_url + url
        self.__before_request()
        resp = self.__session.put(url, json=data)
        return decode_response(resp)

    def get(self, url: str, params: dict = None):
        """
        get请求
        """
        url = self.base_url + url
        self.__before_request()
        resp = self.__session.get(url, params=params)
        return decode_response(resp)

    def patch(self, url: str, data: dict = None):
        """
        patch请求
        """
        url = self.base_url + url
        self.__before_request()
        resp = self.__session.patch(url, json=data)
        return decode_response(resp)

    # ---------------------------------- 对象存储方法 ----------------------------------

    def __get_cos(self):
        self.__cos = CosClient(
            data=self.get(f"/project/{self.groupname}/{self.projname}/runs/{self.exp_id}/sts"),
        )

    def upload(self, buffer: MediaBuffer):
        """
        上传文件，需要注意的是file_path应该为unix风格而不是windows风格
        :param buffer: 自定义文件内存对象
        """
        if self.__cos.should_refresh:
            self.__get_cos()
        return self.__cos.upload(buffer)

    def upload_files(self, buffers: List[MediaBuffer]) -> Dict[str, Union[bool, List]]:
        """
        批量上传文件，keys和local_paths的长度应该相等
        :param buffers: 文件内存对象
        :return: 返回上传结果, 包含success_all和detail两个字段，detail为每一个文件的上传结果（通过index索引对应）
        """
        if self.__cos.should_refresh:
            swanlog.debug("Refresh cos...")
            self.__get_cos()
        return self.__cos.upload_files(buffers)

    # ---------------------------------- 接入后端api ----------------------------------

    def mount_project(self, name: str, username: str = None, public: bool = None):
        """
        创建项目，如果项目已存在，则获取项目信息
        :param name: 项目名称
        :param username: 项目所属的用户名
        :param public: 项目是否公开
        :return: 项目信息
        """
        with Status("Getting project...", spinner="dots"):
            try:
                data = {"name": name}
                if username is not None:
                    data["username"] = username
                if public is not None:
                    data["visibility"] = "PUBLIC" if public else "PRIVATE"
                resp = self.post(f"/project", data=data)
            except ApiError as e:
                if e.resp.status_code == 409:
                    # 项目已经存在，从对象中解析信息
                    resp = decode_response(e.resp)
                elif e.resp.status_code == 404 and e.resp.reason == "Not Found":
                    # WARNING: 早期 （私有化） swanlab 后端没有 /project 接口，需要使用 /project/{username} 接口，此时没有默认空间的特性
                    self.__groupname = self.__groupname if username is None else username
                    try:
                        visibility = "PUBLIC" if public else "PRIVATE"
                        resp = self.post(f"/project/{self.groupname}", data={"name": name, "visibility": visibility})
                    except ApiError as e:
                        # 如果为409，表示已经存在，获取项目信息
                        if e.resp.status_code == 409:
                            resp = self.get(f"/project/{self.groupname}/{name}")
                        elif e.resp.status_code == 404:
                            # 组织/用户不存在
                            raise ValueError(f"Space `{self.groupname}` not found")
                        elif e.resp.status_code == 403:
                            # 权限不足
                            raise ValueError(f"Space permission denied: " + self.groupname)
                        else:
                            raise e
                    return ProjectInfo(resp)
                else:
                    # 此接口为后端处理，sdk 在理论上不会出现其他错误，因此不需要处理其他错误
                    raise e
            # 设置当前项目所属的用户名
            self.__groupname = resp['username']
            # 获取详细信息
            resp = self.get(f"/project/{self.groupname}/{name}")
            project = ProjectInfo(resp)
        self.__proj = project

    def mount_exp(self, exp_name, colors: Tuple[str, str], description: str = None, tags: List[str] = None):
        """
        初始化实验，获取存储信息
        :param exp_name: 所属实验名称
        :param colors: 实验颜色，有两个颜色
        :param description: 实验描述
        :param tags: 实验标签
        """
        with Status("Getting experiment...", spinner="dots"):
            post_data = {
                "name": exp_name,
                "colors": list(colors),
            }
            if description is not None:
                post_data["description"] = description
            if tags is not None:
                post_data["labels"] = [{"name": tag} for tag in tags]

            data = self.post(f"/project/{self.groupname}/{self.__proj.name}/runs", post_data)
            self.__exp = ExperimentInfo(data)
            # 获取cos信息
            self.__get_cos()

    def update_state(self, success: bool):
        """
        更新实验状态
        :param success: 实验是否成功
        """
        self.put(
            f"/project/{self.groupname}/{self.projname}/runs/{self.exp_id}/state",
            {"state": "FINISHED" if success else "CRASHED", "from": "sdk"},
        )


client: Optional["Client"] = None
"""
一个进程只有一个客户端对象
"""


def create_client(login_info: auth.LoginInfo) -> Client:
    """
    创建客户端对象
    """
    global client
    client = Client(login_info)
    return client


def get_client() -> Client:
    """
    获取客户端对象
    :return: client
    """
    global client
    if client is None:
        raise ValueError("client object is not initialized")
    return client


def reset_client():
    """
    重置client对象
    """
    global client
    client = None


def sync_error_handler(func):
    """
    在一些接口中我们不希望线程奔溃，而是返回一个错误对象
    """

    def wrapper(*args, **kwargs) -> Tuple[Optional[Union[dict, str]], Optional[Exception]]:
        try:
            # 在装饰器中调用被装饰的异步函数
            result = func(*args, **kwargs)
            return result, None
        except requests.exceptions.Timeout:
            return None, NetworkError()
        except requests.exceptions.ConnectionError:
            return None, NetworkError()
        except Exception as e:
            return None, e

    return wrapper


__all__ = [
    "get_client",
    "reset_client",
    "create_client",
    "sync_error_handler",
    "decode_response",
    "CosClient",
    "Client",
]
