"""
ImageFolder dataset implementations for the image
classification field in computer vision.
"""

from typing import Callable, Iterable, NamedTuple, Union, Tuple, Dict
import os
import glob
import random
import numpy

from neuralmagicML.utils import clean_path
from neuralmagicML.utils.datasets import (
    IMAGENET_RGB_MEANS,
    IMAGENET_RGB_STDS,
)
from neuralmagicML.tensorflow.utils import tf_compat, tf_compat_div
from neuralmagicML.tensorflow.datasets.dataset import Dataset
from neuralmagicML.tensorflow.datasets.helpers import (
    resize,
    random_scaling_crop,
    center_square_crop,
)
from neuralmagicML.tensorflow.datasets.registry import DatasetRegistry


__all__ = ["imagenet_normalizer", "ImageFolderDataset", "SplitsTransforms"]


SplitsTransforms = NamedTuple(
    "SplitsTransforms",
    [
        ("train", Union[Iterable[Callable], None]),
        ("val", Union[Iterable[Callable], None]),
    ],
)


def imagenet_normalizer(img):
    """
    Normalize an image using mean and std of the imagenet dataset

    :param img: The input image to normalize
    :return: The normalized image
    """
    img = tf_compat_div(img, 255.0)
    means = tf_compat.constant(IMAGENET_RGB_MEANS, dtype=tf_compat.float32)
    stds = tf_compat.constant(IMAGENET_RGB_STDS, dtype=tf_compat.float32)
    img = tf_compat_div(tf_compat.subtract(img, means), stds)

    return img


@DatasetRegistry.register(
    key=["imagefolder"],
    attributes={
        "transform_means": IMAGENET_RGB_MEANS,
        "transform_stds": IMAGENET_RGB_STDS,
    },
)
class ImageFolderDataset(Dataset):
    """
    Implementation for loading an image folder structure into a dataset.

    | Image folders should be of the form:
    |   root/class_x/xxx.ext
    |   root/class_x/xxy.ext
    |   root/class_x/xxz.ext
    |
    |   root/class_y/123.ext
    |   root/class_y/nsdf3.ext
    |   root/class_y/asd932_.ext

    :param root: the root location for the dataset's images to load
    :param train: True to load the training dataset from the root,
        False for validation
    :param image_size: the size of the image to reshape to
    :param pre_resize_transforms: transforms to be applied before resizing the image
    :param post_resize_transforms: transforms to be applied after resizing the image
    """

    def __init__(
        self,
        root: str,
        train: bool,
        image_size: int = 224,
        pre_resize_transforms: Union[SplitsTransforms, None] = SplitsTransforms(
            train=(
                random_scaling_crop(),
                tf_compat.image.random_flip_left_right,
                tf_compat.image.random_flip_up_down,
            ),
            val=None,
        ),
        post_resize_transforms: Union[SplitsTransforms, None] = SplitsTransforms(
            train=(imagenet_normalizer,),
            val=(
                center_square_crop(),
                imagenet_normalizer,
            ),
        ),
    ):
        self._root = os.path.join(clean_path(root), "train" if train else "val")
        if not os.path.exists(self._root):
            raise ValueError("Data set folder {} must exist".format(self._root))
        self._train = train
        self._image_size = image_size
        self._pre_resize_transforms = pre_resize_transforms
        self._post_resize_transforms = post_resize_transforms

        self._num_images = len(
            [None for _ in glob.glob(os.path.join(self._root, "*", "*"))]
        )
        self._num_classes = len(
            [None for _ in glob.glob(os.path.join(self._root, "*", ""))]
        )

    def __len__(self):
        return self._num_images

    @property
    def root(self) -> str:
        """
        :return: the root location for the dataset's images to load
        """
        return self._root

    @property
    def train(self) -> bool:
        """
        :return: True to load the training dataset from the root, False for validation
        """
        return self._train

    @property
    def image_size(self) -> int:
        """
        :return: the size of the images to resize to
        """
        return self._image_size

    @property
    def pre_resize_transforms(self) -> SplitsTransforms:
        """
        :return: transforms to be applied before resizing the image
        """
        return self._pre_resize_transforms

    @property
    def post_resize_transforms(self) -> SplitsTransforms:
        """
        :return: transforms to be applied after resizing the image
        """
        return self._post_resize_transforms

    @property
    def num_images(self) -> int:
        """
        :return: the number of images found for the dataset
        """
        return self._num_images

    @property
    def num_classes(self):
        """
        :return: the number of classes found for the dataset
        """
        return self._num_classes

    def processor(self, file_path: tf_compat.Tensor, label: tf_compat.Tensor):
        """
        :param file_path: the path to the file to load an image from
        :param label: the label for the given image
        :return: a tuple containing the processed image and label
        """
        with tf_compat.name_scope("img_to_tensor"):
            img = tf_compat.read_file(file_path)

            # Decode and reshape the image to 3 dimensional tensor
            # Note: "expand_animations" not available for TF 1.13 and prior,
            # hence the reshape trick below
            img = tf_compat.image.decode_image(img)
            img_shape = tf_compat.shape(img)
            img = tf_compat.reshape(img, [img_shape[0], img_shape[1], img_shape[2]])
            img = tf_compat.cast(img, dtype=tf_compat.float32)

        if self.pre_resize_transforms:
            transforms = (
                self.pre_resize_transforms.train
                if self.train
                else self.pre_resize_transforms.val
            )
            if transforms:
                with tf_compat.name_scope("pre_resize_transforms"):
                    for trans in transforms:
                        img = trans(img)

        if self._image_size:
            res_callable = resize((self.image_size, self.image_size))
            img = res_callable(img)

        if self.post_resize_transforms:
            transforms = (
                self.post_resize_transforms.train
                if self.train
                else self.post_resize_transforms.val
            )
            if transforms:
                with tf_compat.name_scope("post_resize_transforms"):
                    for trans in transforms:
                        img = trans(img)

        return img, label

    def creator(self):
        """
        :return: a created dataset that gives the file_path and label for each
            image under self.root
        """
        labels_strs = [
            fold.split(os.path.sep)[-1]
            for fold in glob.glob(os.path.join(self.root, "*"))
        ]
        labels_strs.sort()
        labels_dict = {
            lab: numpy.identity(len(labels_strs))[index].tolist()
            for index, lab in enumerate(labels_strs)
        }
        files_labels = [
            (file, labels_dict[file.split(os.path.sep)[-2]])
            for file in glob.glob(os.path.join(self.root, "*", "*"))
        ]
        random.Random(42).shuffle(files_labels)
        files, labels = zip(*files_labels)
        files = tf_compat.constant(files)
        labels = tf_compat.constant(labels)

        return tf_compat.data.Dataset.from_tensor_slices((files, labels))

    def format_iterator_batch(
        self, iter_batch: Tuple[tf_compat.Tensor, ...]
    ) -> Tuple[Dict[str, tf_compat.Tensor], Dict[str, tf_compat.Tensor]]:
        """
        :param iter_batch: the batch ref returned from the iterator
        :return: a tuple of image and label tensors
        """
        return iter_batch

    def name_scope(self) -> str:
        """
        :return: the name scope the dataset should be built under in the graph
        """
        return "ImageFolderDataset_{}".format(self.root.replace(os.path.sep, "."))
