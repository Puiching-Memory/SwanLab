"""
------example.py------
from swanlab.converter import WandbConverter

wb_converter = WandbConverter()
wb_converter.run(wb_project="WANDB_PROJECT_NAME", wb_entity="WANDB_USERNAME")
"""

import swanlab
from swanlab.log import swanlog as swl


class WandbConverter:
    def __init__(
        self,
        project: str = None,
        workspace: str = None,
        cloud: bool = True,
        logdir: str = None,
        **kwargs,
    ):
        self.project = project
        self.workspace = workspace
        self.cloud = cloud
        self.logdir = logdir

    def parse_wandb_logs(self, wb_project: str, wb_entity: str, wb_run_id: str = None):
        try:
            import wandb
        except ImportError as e:
            raise TypeError(
                "Wandb Converter requires wandb. Install with 'pip install wandb'."
            )
            
        try:
            import pandas as pd
        except ImportError as e:
            raise TypeError(
                "Wandb Converter requires pandas when process wandb logs. Install with 'pip install pandas'."
            )

        client = wandb.Api()

        if wb_run_id is None:
            # process all runs
            runs = client.runs(wb_entity + "/" + wb_project)
        else:
            # get the run by run_id
            run = client.run(f"{wb_entity}/{wb_project}/{wb_run_id}")
            runs = (run,)

        for iter, wb_run in enumerate(runs):
            swl.info(f"Conversion progress: {iter+1}/{len(runs)}")

            if swanlab.get_run() is None:
                swanlab_run = swanlab.init(
                    project=wb_project if self.project is None else self.project,
                    workspace=self.workspace,
                    experiment_name=wb_run.name,
                    description=wb_run.notes,
                    mode="cloud" if self.cloud else "local",
                    logdir=self.logdir,
                )
            else:
                swanlab_run = swanlab.get_run()
                
            try:
                wb_run_metadata = {"wandb_metadata": wb_run.metadata}
            except:
                wb_run_metadata = {}

            wb_config = {
                "wandb_run_id": wb_run.id,
                "wandb_run_name": wb_run.name,
                "Created Time": wb_run.created_at,
                "wandb_user": wb_run.user,
                "wandb_tags": wb_run.tags,
                "wandb_url": wb_run.url,
            }
            wb_config.update(wb_run_metadata)

            swanlab_run.config.update(wb_config)
            swanlab_run.config.update(wb_run.config)

            # Get the first history record to extract available keys
            history = wb_run.history(stream="default")
            if len(history) > 0:
                # 检查 history 是否为 DataFrame 类型
                if isinstance(history, pd.DataFrame):
                    # 如果是 DataFrame，直接获取列名
                    keys = [key for key in history.columns if not key.startswith("_")]
                else:
                    # 原来的逻辑，假设是字典列表
                    keys = [key for key in history[0].keys() if not key.startswith("_")]
            else:
                keys = []

            # 记录标量指标
            for record in wb_run.scan_history():
                step = record.get("_step")
                for key in keys:
                    value = record.get(key)
                    # 如果value是None或者是dict类型，则跳过
                    if value is None or isinstance(value, dict) or not isinstance(value, (float, int)):
                        # 如果是多媒体数据，如图像，value是这个格式
                        # image {'format': 'png', 'path': 'media/images/image_13_3bbb7517118b6af0307c.png', 'sha256': '3bbb7517118b6af0307cbe1b26f6d94b68797874112de716df4b5b50e01ddc24', 'size': 30168, 'height': 100, 'width': 100, '_type': 'image-file'}
                        continue
                    swanlab_run.log({key: value}, step=step)

            # 结束此轮实验
            swanlab_run.finish()

    def run(self, wb_project: str, wb_entity: str, wb_run_id: str = None):
        swl.info("Start converting Wandb Runs to SwanLab...")
        self.parse_wandb_logs(
            wb_project=wb_project,
            wb_entity=wb_entity,
            wb_run_id=wb_run_id,
        )
        swl.info("Finished converting Wandb Runs to SwanLab.")
