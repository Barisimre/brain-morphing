from src.trainings.segmentation import train_segmentation
from src.trainings.centering import optimize_centers
import wandb

if __name__ == '__main__':


    run_name = "new_ssim"
    # location = "/home/baris/Documents/brain-morphing"
    location = "/home/imreb/brain-morphing"
    # location = "/home/baris/Documents/work/brain-morphing"

    wandb.init(project="debug",
               entity="barisimre",
               name=run_name)

    # train_segmentation(batch_size=2, run_name=run_name, location=location, slice_thickness="large", dims=3)
    optimize_centers(location=location, run_name=run_name, batch_size=1, num_epochs=75)
